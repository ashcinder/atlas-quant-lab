package supervisor

import (
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/message"
	"blockEmulator/params"
	"blockEmulator/supervisor/Broker2Earn"
	"fmt"
	"github.com/gin-gonic/gin"
	"github.com/jinzhu/gorm"
	"math/big"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

var Queue = make([]*core.Transaction, 0)
var QueueMutex sync.Mutex
var restBrokerRawMegPool []*message.BrokerRawMeg

func SubmitToB2E(tx *core.Transaction) {
	QueueMutex.Lock()
	Queue = append(Queue, tx)
	QueueMutex.Unlock()
}
func (d *Supervisor) ScheduleB2E() {
	for {
		time.Sleep(5 * time.Second)

		QueueMutex.Lock()
		if len(Queue) == 0 {
			QueueMutex.Unlock()
			continue
		}
		queueCopy := make([]*core.Transaction, len(Queue))
		copy(queueCopy, Queue)
		Queue = Queue[:0]
		QueueMutex.Unlock()
		dealTxByBroker(queueCopy)
	}
}
func dealTxByBroker(txs []*core.Transaction) (itxs []*core.Transaction) {
	itxs = make([]*core.Transaction, 0)
	brokerRawMegs := make([]*message.BrokerRawMeg, 0)
	for _, item := range restBrokerRawMegPool {
		brokerRawMegs = append(brokerRawMegs, item)
	}
	restBrokerRawMegPool = make([]*message.BrokerRawMeg, 0)

	for _, tx := range txs {
		if tx.Recipient == tx.Sender {
			continue
		}
		rSid := fetchModifiedMap(tx.Recipient)
		sSid := fetchModifiedMap(tx.Sender)


		//if rSid != sSid && !bcm.Broker.IsBroker(tx.Recipient) && !bcm.Broker.IsBroker(tx.Sender) {
		if rSid != sSid {
			brokerRawMeg := &message.BrokerRawMeg{
				Tx:     tx,
				Broker: "123",
			}
			brokerRawMegs = append(brokerRawMegs, brokerRawMeg)
		} else {
			if IsBroker(tx.Recipient) || IsBroker(tx.Sender) {
				tx.HasBroker = true
				tx.SenderIsBroker = IsBroker(tx.Sender)
			}
			itxs = append(itxs, tx)
		}
	}

	var BrokerBalance = make(map[string]map[uint64]*big.Int)
	var LockBalance = make(map[string]map[uint64]*big.Int)
	var ProfitBalance = make(map[string]map[uint64]*big.Float)
	var brokers []Broker
	tx := db.DB.Begin()
	if err := tx.Model(Broker{}).Set("gorm:query_option", "FOR UPDATE").Find(&brokers).Error; err != nil {
		tx.Rollback()
		return nil
	}
	if len(brokers) == 0 {
		tx.Rollback()
		return nil
	}
	var cc Config
	db.DB.Model(cc).Where("config = ?","shardid_senior").Find(&cc)
	shardNum, _:= strconv.Atoi(cc.Value)

	for _, broker := range brokers {
		split := strings.Split(broker.BrokerBalance, ";")
		if len(split) < shardNum {
			len1:= len(split)
			for i := 0; i < shardNum - len1; i++ {
				split = append(split, "0")
			}
		}


		BrokerBalance[broker.Addr] = make(map[uint64]*big.Int)
		for idx, balance := range split {
			bigint := new(big.Int)
			bigint.SetString(balance,10)
			BrokerBalance[broker.Addr][uint64(idx)] = bigint
		}



		split2 := strings.Split(broker.LockBalance, ";")

		if len(split2) < shardNum {
			len2:= len(split2)
			for i := 0; i < shardNum - len2; i++ {
				split2 = append(split2, "0")
			}
		}


		LockBalance[broker.Addr] = make(map[uint64]*big.Int)
		for idx, balance := range split2 {
			bigint := new(big.Int)
			bigint.SetString(balance, 10)
			LockBalance[broker.Addr][uint64(idx)] = bigint
		}

		split3 := strings.Split(broker.ProfitBalance, ";")

		if len(split3) < shardNum {
			len3:= len(split3)
			for i := 0; i < shardNum - len3; i++ {
				split3 = append(split3, "0")
			}
		}

		ProfitBalance[broker.Addr] = make(map[uint64]*big.Float)
		for idx, balance := range split3 {
			bigint := new(big.Float)
			bigint.SetPrec(512)
			bigint.SetString(balance)
			ProfitBalance[broker.Addr][uint64(idx)] = bigint
		}
	}

	alloctedBrokerRawMegs, restBrokerRawMeg := Broker2Earn.B2E(brokerRawMegs, BrokerBalance)
	if restBrokerRawMeg != nil {
		for _, item := range restBrokerRawMeg {
			restBrokerRawMegPool = append(restBrokerRawMegPool, item)
		}
	}
	allocatedTxs := GenerateAllocatedTx(alloctedBrokerRawMegs, BrokerBalance)
	if len(alloctedBrokerRawMegs) != 0 {
		handleAllocatedTx(allocatedTxs, BrokerBalance)
		//lockToken(alloctedBrokerRawMegs,BrokerBalance,LockBalance,tx)
		handleBrokerRawMag(alloctedBrokerRawMegs)
	} else {

	}

	for _, t := range alloctedBrokerRawMegs {
		//ssid := fetchModifiedMap(t.Tx.Sender)
		var loc Location
		db.DB.Model(loc).Where("addr = ?",t.Tx.Sender).Find(&loc)
		ssid:=loc.Location
		fee1 := new(big.Int)
		fee1.Set(t.Tx.Fee)
		fee2 := new(big.Float)
		fee2.SetInt(fee1)
		Brokerage := new(big.Float)
		Brokerage.SetString(params.Brokerage)
		fee2 = fee2.Mul(fee2, Brokerage)
		if ProfitBalance[t.Broker][ssid] !=nil{
			ProfitBalance[t.Broker][ssid].Add(ProfitBalance[t.Broker][ssid], fee2)
		}
	}
	for _, broker := range brokers {
		BrokerBalance_ := ""

		len1:= len(BrokerBalance[broker.Addr])
		for i := 0; i < len1; i++ {
			balance := BrokerBalance[broker.Addr][uint64(i)]
			BrokerBalance_ = BrokerBalance_ + balance.String()
			if i != len1-1 {
				BrokerBalance_ = BrokerBalance_ + ";"
			}
		}

		//for idx, balance := range BrokerBalance[broker.Addr] {
		//	BrokerBalance_ = BrokerBalance_ + balance.String()
		//	if int(idx) != (len(BrokerBalance[broker.Addr]) - 1) {
		//		BrokerBalance_ = BrokerBalance_ + ";"
		//	}
		//}
		LockBalance_ := ""
		len2:= len(LockBalance[broker.Addr])
		for i := 0; i < len2; i++ {
			balance := LockBalance[broker.Addr][uint64(i)]
			LockBalance_ = LockBalance_ + balance.String()
			if i != len2-1 {
				LockBalance_ = LockBalance_ + ";"
			}
		}


		//for idx, balance := range LockBalance[broker.Addr] {
		//	LockBalance_ = LockBalance_ + balance.String()
		//	if int(idx) != (len(LockBalance[broker.Addr]) - 1) {
		//		LockBalance_ = LockBalance_ + ";"
		//	}
		//}
		ProfitBalance_ := ""
		len3:= len(ProfitBalance[broker.Addr])
		for i := 0; i < len3; i++ {
			balance := ProfitBalance[broker.Addr][uint64(i)]
			ProfitBalance_ = ProfitBalance_ + balance.Text('f',-1)
			if i != len3-1 {
				ProfitBalance_ = ProfitBalance_ + ";"
			}
		}

		//for idx, balance := range ProfitBalance[broker.Addr] {
		//	ProfitBalance_ = ProfitBalance_ + balance.Text('f', -1)
		//	if int(idx) != (len(ProfitBalance[broker.Addr]) - 1) {
		//		ProfitBalance_ = ProfitBalance_ + ";"
		//	}
		//}
		broker.BrokerBalance = BrokerBalance_
		broker.LockBalance = LockBalance_
		broker.ProfitBalance = ProfitBalance_
		broker.Version += 1
		tx.Model(broker).Where("id = ?", broker.Id).Update(&broker)
	}

	tx.Commit()
	return itxs

}

func handleBrokerRawMag(brokerRawMags []*message.BrokerRawMeg) {}

func lockToken(alloctedBrokerRawMegs []*message.BrokerRawMeg, BrokerBalance map[string]map[uint64]*big.Int, LockBalance map[string]map[uint64]*big.Int, TX *gorm.DB) {
	for _, brokerRawMeg := range alloctedBrokerRawMegs {
		tx := brokerRawMeg.Tx
		brokerAddress := brokerRawMeg.Broker
		rSid := fetchModifiedMap(tx.Recipient)
		if !IsBroker_(brokerAddress, TX) {
			continue
		}
		LockBalance[brokerAddress][rSid].Add(LockBalance[brokerAddress][rSid], tx.Value)
		BrokerBalance[brokerAddress][rSid].Sub(BrokerBalance[brokerAddress][rSid], tx.Value)
	}
}
func handleAllocatedTx(alloctedTx map[uint64][]*core.Transaction, BrokerBalance map[string]map[uint64]*big.Int) {

	//bcm.BrokerBalanceLock.Lock()

	for shardId, txs := range alloctedTx {
		for _, tx := range txs {
			if tx.IsAllocatedSender {
				if BrokerBalance[tx.Sender][shardId] !=nil{
					BrokerBalance[tx.Sender][shardId].Sub(BrokerBalance[tx.Sender][shardId], tx.Value)
				}

			}
			if tx.IsAllocatedRecipent {
				if BrokerBalance[tx.Recipient][shardId] !=nil{
					BrokerBalance[tx.Recipient][shardId].Add(BrokerBalance[tx.Recipient][shardId], tx.Value)
				}

			}
		}

		//it := message.InjectTxs{
		//	Txs:       txs,
		//	ToShardID: shardId,
		//}
		//itByte, err := json.Marshal(it)
		//if err != nil {
		//	log.Panic(err)
		//}
		//send_msg := message.MergeMessage(message.CInjectHead, itByte)
		//go networks.TcpDial(send_msg, bcm.IpNodeTable[shardId][0])
		//time.Sleep(time.Second)
	}
	//bcm.BrokerBalanceLock.Unlock()

}

func GenerateAllocatedTx(alloctedBrokerRawMegs []*message.BrokerRawMeg, BrokerBalance map[string]map[uint64]*big.Int) map[uint64][]*core.Transaction {
	//bcm.Broker.BrokerBalance
	//brokerNewBalance := make(map[string]map[uint64]*big.Int)
	brokerChange := make(map[string]map[uint64]*big.Int)
	brokerPeekChange := make(map[string]map[uint64]*big.Int)

	// 1. init
	alloctedTxs := make(map[uint64][]*core.Transaction)
	for i := 0; i < params.ShardNum; i++ {
		alloctedTxs[uint64(i)] = make([]*core.Transaction, 0)
	}

	//bcm.BrokerBalanceLock.Lock()
	for brokerAddress, shardMap := range BrokerBalance {
		//brokerNewBalance[brokerAddress] = make(map[uint64]*big.Int)
		brokerChange[brokerAddress] = make(map[uint64]*big.Int)
		brokerPeekChange[brokerAddress] = make(map[uint64]*big.Int)
		for shardId, balance := range shardMap {
			//brokerNewBalance[brokerAddress][shardId] = new(big.Int).Set(balance)
			brokerChange[brokerAddress][shardId] = big.NewInt(0)
			brokerPeekChange[brokerAddress][shardId] = new(big.Int).Set(balance)
		}

	}
	//bcm.BrokerBalanceLock.Unlock()

	for _, brokerRawMeg := range alloctedBrokerRawMegs {
		//var loc1 Location
		var loc2 Location
		//db.DB.Model(loc1).Where("addr = ?",brokerRawMeg.Tx.Sender).Find(&loc1)
		db.DB.Model(loc2).Where("addr = ?",brokerRawMeg.Tx.Recipient).Find(&loc2)
		//sSid := fetchModifiedMap(brokerRawMeg.Tx.Sender)
		//rSid := fetchModifiedMap(brokerRawMeg.Tx.Recipient)
		//sSid := loc1.Location
		rSid := loc2.Location
		brokerAddress := brokerRawMeg.Broker

		//brokerNewBalance[brokerAddress][sSid].Add(brokerNewBalance[brokerAddress][sSid], brokerRawMeg.Tx.Value)
		//brokerNewBalance[brokerAddress][rSid].Sub(brokerNewBalance[brokerAddress][rSid], brokerRawMeg.Tx.Value)

		brokerPeekChange[brokerAddress][rSid].Sub(brokerPeekChange[brokerAddress][rSid], brokerRawMeg.Tx.Value)
	}

	// generate tx
	//bcm.BrokerBalanceLock.Lock()

	for brokerAddress, shardMap := range brokerPeekChange {
		for shardId, _ := range shardMap {

			peekBalance := brokerPeekChange[brokerAddress][shardId]

			if peekBalance.Cmp(big.NewInt(0)) < 0 {
				// If FromShard does not have enough balance, find another shard to cover the deficit

				deficit := new(big.Int).Set(peekBalance)
				deficit.Abs(deficit)
				for id, balance := range brokerPeekChange[brokerAddress] {
					if deficit.Cmp(big.NewInt(0)) == 0 {
						break
					}
					if id != shardId && balance.Cmp(big.NewInt(0)) > 0 {
						tmpValue := new(big.Int).Set(deficit)
						if balance.Cmp(deficit) < 0 {
							tmpValue.Set(balance)
							deficit.Sub(deficit, balance)
						} else {
							deficit.SetInt64(0)
						}
						//brokerChange[brokerAddress][id].Sub(brokerChange[brokerAddress][id], tmpValue)
						//brokerChange[brokerAddress][shardId].Add(brokerChange[brokerAddress][shardId], tmpValue)
						//brokerNewBalance[brokerAddress][id].Sub(brokerNewBalance[brokerAddress][id], tmpValue)
						//brokerNewBalance[brokerAddress][shardId].Add(brokerNewBalance[brokerAddress][shardId], tmpValue)

						brokerPeekChange[brokerAddress][id].Sub(brokerPeekChange[brokerAddress][id], tmpValue)
						brokerPeekChange[brokerAddress][shardId].Add(brokerPeekChange[brokerAddress][shardId], tmpValue)

						brokerChange[brokerAddress][id].Sub(brokerChange[brokerAddress][id], tmpValue)
						brokerChange[brokerAddress][shardId].Add(brokerChange[brokerAddress][shardId], tmpValue)
					}
				}
			}
		}

	}
	// generate allocated tx

	for brokerAddress, shardMap := range brokerChange {
		for shardId, _ := range shardMap {

			diff := brokerChange[brokerAddress][shardId]

			if diff.Cmp(big.NewInt(0)) == 0 {
				continue
			}
			//tx := core.NewTransaction(brokerAddress, brokerAddress, new(big.Int).Abs(diff), uint64(bcm.nowDataNum), big.NewInt(0))
			tx := core.NewTransaction(brokerAddress, brokerAddress, new(big.Int).Abs(diff), 0, time.Now())

			//bcm.nowDataNum++
			if diff.Cmp(big.NewInt(0)) < 0 {
				tx.IsAllocatedSender = true
			} else {
				tx.IsAllocatedRecipent = true
			}
			alloctedTxs[shardId] = append(alloctedTxs[shardId], tx)
		}

	}

	//bcm.BrokerBalanceLock.Unlock()
	return alloctedTxs
}
func IsBroker_(addr string, TX *gorm.DB) bool {
	var broker Broker
	if err := TX.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		return false
	}
	return true
}

func IsBroker(addr string) bool {
	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		return false
	}
	return true
}

func fetchModifiedMap(key string) uint64 {
	var loc Location
	db.DB.Model(loc).Where("addr = ?", key).Find(&loc)
	return loc.Location
	//return uint64(utils.Addr2Shard(key))
}

func withdrawbroker(c *gin.Context) {
	var req WithdrawReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}
	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "success"})
		return
	}

	tx := db.DB.Begin()
	if err := tx.Model(broker).Where("addr = ?", addr).Set("gorm:query_option", "FOR UPDATE").First(&broker).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}
	var acc Account
	if err := tx.Model(acc).Where("addr = ?", addr).Set("gorm:query_option", "FOR UPDATE").First(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}
	bf := new(big.Float)
	bf.SetPrec(512)
	brokerbalance := strings.Split(broker.BrokerBalance, ";")
	for _, balance := range brokerbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"message": "failed"})
			return
		}
		bf.Add(bf, bff)
	}
	lockbalance := strings.Split(broker.LockBalance, ";")
	for _, balance := range lockbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"message": "failed"})
			return
		}
		bf.Add(bf, bff)
	}
	profitbalance := strings.Split(broker.ProfitBalance, ";")
	for _, balance := range profitbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"message": "failed"})
			return
		}
		bf.Add(bf, bff)
	}
	bff := new(big.Float)
	bff.SetPrec(512)
	_, success := bff.SetString(acc.Value)
	if !success {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}
	bff.Add(bff, bf)
	acc.Value = bff.Text('f', -1)
	acc.Version += 1
	if err := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}
	var transaction TX
	transaction.From = "B2E"
	transaction.To = addr
	transaction.Value = bf.Text('f', -1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}
	if err := tx.Model(broker).Where("id = ?", broker.Id).Delete(&Broker{}).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "failed"})
		return
	}

	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"message": "success"})
}
func Withdrawbroker2(addr string) {
	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		return
	}

	tx := db.DB.Begin()
	if err := tx.Model(broker).Where("addr = ?", addr).Set("gorm:query_option", "FOR UPDATE").First(&broker).Error; err != nil {
		tx.Rollback()
		return
	}
	var acc Account
	if err := tx.Model(acc).Where("addr = ?", addr).Set("gorm:query_option", "FOR UPDATE").First(&acc).Error; err != nil {
		tx.Rollback()
		return
	}
	bf := new(big.Float)
	bf.SetPrec(512)
	brokerbalance := strings.Split(broker.BrokerBalance, ";")
	for _, balance := range brokerbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()
			return
		}
		bf.Add(bf, bff)
	}
	lockbalance := strings.Split(broker.LockBalance, ";")
	for _, balance := range lockbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()

			return
		}
		bf.Add(bf, bff)
	}
	profitbalance := strings.Split(broker.ProfitBalance, ";")
	for _, balance := range profitbalance {
		bff := new(big.Float)
		bff.SetPrec(512)
		_, success := bff.SetString(balance)
		if !success {
			tx.Rollback()

			return
		}
		bf.Add(bf, bff)
	}
	bff := new(big.Float)
	bff.SetPrec(512)
	_, success := bff.SetString(acc.Value)
	if !success {
		tx.Rollback()

		return
	}
	bff.Add(bff, bf)
	acc.Value = bff.Text('f', -1)
	acc.Version += 1
	if err := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; err != nil {
		tx.Rollback()

		return
	}
	var transaction TX
	transaction.From = "B2E"
	transaction.To = addr
	transaction.Value = bf.Text('f', -1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()

		return
	}
	if err := tx.Model(broker).Where("id = ?", broker.Id).Delete(&Broker{}).Error; err != nil {
		tx.Rollback()

		return
	}

	tx.Commit()

}
func querybrokerprofit(c *gin.Context) {
	var req QueryProfitReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}
	response := make(map[string]string)
	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		c.JSON(http.StatusOK, response)
		return
	}
	profitbalance := strings.Split(broker.ProfitBalance, ";")
	brokerbalance := strings.Split(broker.BrokerBalance, ";")
	lockbalance := strings.Split(broker.LockBalance, ";")
	if len(profitbalance) != len(brokerbalance) || len(brokerbalance) != len(lockbalance) {
		c.JSON(http.StatusOK, response)
		return
	}

	var cc Config
	db.DB.Model(cc).Where("config = ?","shardid_senior").Find(&cc)
	shardNum,_ := strconv.Atoi(cc.Value)
	if len(profitbalance) < shardNum {
		len1:= len(profitbalance)
		for i := 0; i < shardNum - len1; i++ {
			profitbalance = append(profitbalance, "0")
			brokerbalance = append(brokerbalance, "0")
			lockbalance = append(lockbalance, "0")
		}
		s1 := strings.Join(profitbalance, ";")
		s2 := strings.Join(brokerbalance, ";")
		s3 := strings.Join(lockbalance, ";")
		broker.BrokerBalance = s2
		broker.LockBalance = s3
		broker.ProfitBalance = s1
		db.DB.Model(broker).Where("id = ?", broker.Id).Update(&broker)
	}

	for i := 0; i < len(profitbalance); i++ {
		Unit := new(big.Float)
		Unit.SetString(global.Uint)
		Unit2 := new(big.Float)
		Unit2.SetString(global.Uint)
		b1 := profitbalance[i]
		b2 := brokerbalance[i]
		b3 := lockbalance[i]
		b1bigfloat := new(big.Float)
		b1bigfloat.SetString(b1)
		b2bigint := new(big.Float)
		b2bigint.SetString(b2)
		b3bigint := new(big.Float)
		b3bigint.SetString(b3)
		b4 := new(big.Float)
		b4.Add(b2bigint, b3bigint)
		b1bigfloat.Quo(b1bigfloat, Unit2)
		b4.Quo(b4, Unit)

		response[fmt.Sprintf("%d", i)] = b1bigfloat.Text('f', -1) + "/" + b4.Text('f',-1)
	}
	c.JSON(http.StatusOK, response)

}

var StakeLock sync.Mutex

func stake(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req StakeReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"message": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.Value

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"message": "addr not exist"})
		return
	}
	bf := new(big.Float)
	bf.SetPrec(512)
	_, success := bf.SetString(req.Value)
	if !success {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid Value. Format not correct."})
		return
	}
	if bf.Signbit() {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid Value. Should not be negative."})
		return
	}
	if bf.Cmp(big.NewFloat(0)) == 0 {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid Value. Should not be zero."})
		return
	}
	if bf.Cmp(big.NewFloat(100000000)) == 1 {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid Value. Too large."})
		return
	}

	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Not a broker."})
		return
	}

	//i := new(big.Int)
	//i, _ = bf.Int(i)

	//if i.Cmp(big.NewInt(0)) == 0 {
	//	c.JSON(http.StatusOK, gin.H{"message": "Failed. Please stake more tokens."})
	//	return
	//}

	var cc Config
	db.DB.Where("config = ?", "shardid_senior").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)

	//i = floorDiv(i, new(big.Int).SetUint64(uint64(shardNum)))
	//
	//if i.Cmp(big.NewInt(0)) == 0 {
	//	c.JSON(http.StatusOK, gin.H{"message": "Failed. Please stake more tokens."})
	//	return
	//}

	stakestring := bf.Text('f',-1)
	Unit := new(big.Float)
	Unit.SetString(global.Uint)
	bf.Mul(bf, Unit)

	bf.Quo(bf, new(big.Float).SetUint64(uint64(shardNum)))
	aa:=new(big.Int)
	aa,_ = bf.Int(aa)
	bf.SetInt(aa)
	aa.Mul(aa, new(big.Int).SetUint64(uint64(shardNum)))


	StakeLock.Lock()
	defer StakeLock.Unlock()

	d.Lock.RLock()
	defer d.Lock.RUnlock()


	var acc Account
	db.DB.Model(acc).Where("addr = ?", addr).Find(&acc)
	have := new(big.Int)
	have.SetString(acc.Value,10)
	if have.Cmp(aa) == -1 {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Account's balance not enough."})
		return
	}
	have.Sub(have, aa)

	tx := db.DB.Begin()
	res1 := tx.Model(acc).
		Where("id = ? AND version = ?", acc.Id, acc.Version).
		Updates(map[string]interface{}{
			"balance": have.Text(10),
			"version": acc.Version + 1,
		})

	if res1.Error != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Please try again."})
		return
	}

	// 检查是否成功更新了记录
	if res1.RowsAffected == 0 {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Please try again."})
		return
	}

	if err := tx.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Try again later."})
		return
	}

	balancepershard := new(big.Int)
	balancepershard.Quo(aa, new(big.Int).SetUint64(uint64(shardNum)))


	//i := new(big.Int)
	//i, _ = bf.Int(i)
	//i,_=balancepershard.Int(i)
	split := strings.Split(broker.BrokerBalance, ";")
	if len(split) < shardNum {
		for i1 := 0; i1 < shardNum-len(split); i1++ {
			split = append(split, "0")
		}
	}
	for i1 := 0; i1 < len(split); i1++ {
		bigint := new(big.Int)
		bigint.SetString(split[i1],10)
		bigint.Add(balancepershard, bigint)
		split[i1] = bigint.Text(10)
	}

	split2 := strings.Split(broker.LockBalance, ";")
	if len(split2) < shardNum {
		for i1 := 0; i1 < shardNum-len(split2); i1++ {
			split2 = append(split2, "0")
		}
	}

	split3 := strings.Split(broker.ProfitBalance, ";")
	if len(split3) < shardNum {
		for i1 := 0; i1 < shardNum-len(split3); i1++ {
			split3 = append(split3, "0")
		}
	}

	newbrokerbalance := strings.Join(split, ";")
	newlockbalance := strings.Join(split2, ";")
	newprofitbalance := strings.Join(split3, ";")

	res2 := tx.Model(broker).
		Where("id = ? AND version = ?", broker.Id, broker.Version).
		Updates(map[string]interface{}{
			"broker_balance": newbrokerbalance,
			"lock_balance":   newlockbalance,
			"profit_balance": newprofitbalance,
			"version":        broker.Version + 1,
		})

	if res2.Error != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Please try again."})
		return
	}

	// 检查是否成功更新了记录
	if res2.RowsAffected == 0 {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Please try again."})
		return
	}

	var transaction TX
	transaction.From = addr
	transaction.To = "B2E"
	transaction.Value = bf.Text('f',-1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Try again later."})
		return
	}

	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"message": "Successfully stake " + stakestring + "BKC to B2E."})

}

func floorDiv(x, y *big.Int) *big.Int {
	if y.Sign() == 0 {
		//panic("division by zero")
		fmt.Println("division by zero")
		return x
	}

	// 计算余数
	mod := new(big.Int)
	mod.Mod(x, y)

	// 如果余数为 0，说明已经可以整除
	if mod.Sign() == 0 {
		return x
	}

	// 否则：x = x - mod(x, y)
	result := new(big.Int).Sub(x, mod)
	return result
}
func applybroker(c *gin.Context) {
	var req ApplybrokerReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}
	var cc Config
	db.DB.Where("config = ?", "shardid_senior").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)
	s := ""
	for i := 0; i < shardNum; i++ {
		s = s + "0"
		if i != shardNum-1 {
			s = s + ";"
		}
	}
	var broker Broker
	broker.Addr = addr
	broker.BrokerBalance = s
	broker.LockBalance = s
	broker.ProfitBalance = s
	broker.Version = 0

	tx := db.DB.Begin()
	if err := tx.Model(broker).Create(&broker).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"message": "申请成为Broker失败"})
		return
	}
	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"message": "申请成为Broker成功"})
	return
}
func queryisbroker(c *gin.Context) {
	//d := c.MustGet("supervisor").(*Supervisor)
	var req QueryisbrokerReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}

	var broker Broker
	if err := db.DB.Model(broker).Where("addr = ?", addr).Find(&broker).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"is_broker": "false"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"is_broker": "true"})

}
