package supervisor

import (
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/message"
	"blockEmulator/partition"
	"blockEmulator/supervisor/committee"
	"encoding/json"
	"fmt"
	"math/big"
	"math/rand"
	"net"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

func (d *Supervisor) PackTXs() {
	for {
		txs := d.TXPool.PackTxs(10000)
		if len(txs) > 0 {
			d.processTxs(txs)
		}
		time.Sleep(time.Second * 10)
	}

}

func (d *Supervisor) processTxs(txs []*core.Transaction) {
	d.Lock.Lock()
	defer d.Lock.Unlock()

	mm := make(map[string]bool)
	for _, tx := range txs {
		if tx.SC {
			continue
		}
		mm[tx.Sender] = true
		mm[tx.Recipient] = true
	}
	mm2 := make(map[uint64][]string)
	for k, _ := range mm {
		var loc Location
		if err := db.DB.Model(loc).Where("addr = ? ", k).Find(&loc).Error; err != nil {
			continue
		}
		if _, ok := mm2[loc.Location]; !ok {
			mm2[loc.Location] = make([]string, 0)
		}
		mm2[loc.Location] = append(mm2[loc.Location], k)
	}

	keys := make([]uint64, 0, len(mm2))
	for k := range mm2 {
		keys = append(keys, k)
	}

	// 2. 对 key 进行排序
	sort.Slice(keys, func(i, j int) bool {
		return keys[i] < keys[j]
	})

	// 3. 按照排序后的 key 顺序访问 map
	//for _, k := range keys {
	//if len(d.SmallStatedb) <= int(k){
	//	continue
	//}
	//accs := mm2[k]
	//var hash Config
	//db.DB.Model(hash).Where("config = ?","shard_"+strconv.Itoa(int(k))+"_root").Find(&hash)
	//root, _ := hex.DecodeString(hash.Value)
	//statedb, _ := state.New(common.Hash(root), d.SmallStatedb[k])
	//for _, acc := range accs {
	//	var accdo Account
	//	db.DB.Model(accdo).Where("addr = ? ",acc).Find(&accdo)
	//	bytes, _ := hex.DecodeString(acc)
	//	bigint:=new(big.Int)
	//	bigint.SetString(accdo.Value,10)
	//	fromBig, _ := uint256.FromBig(bigint)
	//	if fromBig != nil{
	//		//statedb.SetBalance(common.Address(bytes),fromBig,tracing.BalanceAddByXBZ)
	//	}
	//}
	//hash2,_:=statedb.Commit(0,false)
	//root2 := hex.EncodeToString(hash2[:])
	//hash.Value = root2
	//db.DB.Model(hash).Where("id = ? ",hash.Id).Update(hash)
	//d.SmallTriedb[k].Commit(hash2,false)
	//var his RootHistory
	//his.ShardId = k
	////his.Root = root2
	//his.Timestamp = time.Now()
	//db.DB.Model(his).Create(&his)
	//}

	for _, tx := range txs {
		if tx.SC {
			continue
		}
		from := tx.Sender
		to := tx.Recipient
		var Loc1 Location
		var Loc2 Location
		db.DB.Model(Loc1).Where("addr = ?", from).First(&Loc1)
		db.DB.Model(Loc2).Where("addr = ?", to).First(&Loc2)
		if Loc1.Location == Loc2.Location {
			var conns []net.Conn
			var locks []*sync.Mutex
			ConnectionMapLock.RLock()
			for i := 0; i < 100; i++ {
				key := strconv.Itoa(int(Loc1.Location)) + ":" + strconv.Itoa(i)
				conn, ok := ConnectionMap[key]
				if !ok {
					break
				}
				if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 != nil {
					continue
				}
				conns = append(conns, conn)
				mutex, _ := ConnectionLockMap[key]
				locks = append(locks, mutex)
			}
			ConnectionMapLock.RUnlock()
			txcopy := tx.DeepCopy()
			txcopy.Flag1 = true
			txcopy.Flag2 = true
			txlist := make([]*core.Transaction, 0)
			txlist = append(txlist, txcopy)
			it := message.InjectTxs{
				Txs:       txlist,
				ToShardID: Loc1.Location,
			}
			itByte, _ := json.Marshal(it)
			send_msg := message.MergeMessage(message.CInject, itByte)
			for idx1, conn := range conns {
				var wg sync.WaitGroup
				wg.Add(1)
				go func() {
					locks[idx1].Lock()
					defer func() {
						locks[idx1].Unlock()
						wg.Done()
					}()
					conn.Write(append(send_msg, '\n'))
				}()
				wg.Wait()
			}
		} else {
			var conns1 []net.Conn
			var locks1 []*sync.Mutex
			var conns2 []net.Conn
			var locks2 []*sync.Mutex
			ConnectionMapLock.RLock()
			for i := 0; i < 100; i++ {
				key := strconv.Itoa(int(Loc1.Location)) + ":" + strconv.Itoa(i)
				conn, ok := ConnectionMap[key]
				if !ok {
					break
				}
				if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 != nil {
					continue
				}
				conns1 = append(conns1, conn)
				mutex, _ := ConnectionLockMap[key]
				locks1 = append(locks1, mutex)
			}
			for i := 0; i < 100; i++ {
				key := strconv.Itoa(int(Loc2.Location)) + ":" + strconv.Itoa(i)
				conn, ok := ConnectionMap[key]
				if !ok {
					break
				}
				if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 != nil {
					continue
				}
				conns2 = append(conns2, conn)
				mutex, _ := ConnectionLockMap[key]
				locks2 = append(locks2, mutex)
			}
			ConnectionMapLock.RUnlock()
			txcopy1 := tx.DeepCopy()
			txcopy2 := tx.DeepCopy()
			txcopy1.Flag1 = true
			txcopy1.Flag2 = false
			txcopy2.Flag2 = true
			txcopy2.Flag1 = false
			txlist1 := make([]*core.Transaction, 0)
			txlist1 = append(txlist1, txcopy1)
			txlist2 := make([]*core.Transaction, 0)
			txlist2 = append(txlist2, txcopy2)
			it1 := message.InjectTxs{
				Txs:       txlist1,
				ToShardID: Loc1.Location,
			}
			it2 := message.InjectTxs{
				Txs:       txlist2,
				ToShardID: Loc2.Location,
			}
			itByte1, _ := json.Marshal(it1)
			itByte2, _ := json.Marshal(it2)
			send_msg1 := message.MergeMessage(message.CInject, itByte1)
			send_msg2 := message.MergeMessage(message.CInject, itByte2)
			for idx1, conn := range conns1 {
				var wg sync.WaitGroup
				wg.Add(1)
				go func() {
					locks1[idx1].Lock()
					defer func() {
						locks1[idx1].Unlock()
						wg.Done()
					}()
					conn.Write(append(send_msg1, '\n'))
				}()
				wg.Wait()
			}
			for idx2, conn := range conns2 {
				var wg sync.WaitGroup
				wg.Add(1)
				go func() {
					locks2[idx2].Lock()
					defer func() {
						locks2[idx2].Unlock()
						wg.Done()
					}()
					conn.Write(append(send_msg2, '\n'))
				}()
				wg.Wait()
			}

		}
	}

}
func IsEthereumAddress(address string) bool {
	// 正则表达式解释：
	// ^        - 字符串开始
	// [0-9a-fA-F] - 匹配16进制字符（不区分大小写）
	// {40}      - 精确匹配40次
	// $        - 字符串结束
	return regexp.MustCompile(`^[0-9a-fA-F]{40}$`).MatchString(address) || regexp.MustCompile(`^[0-9a-fA-F]{39}$`).MatchString(address) || regexp.MustCompile(`^[0-9a-fA-F]{38}$`).MatchString(address) || regexp.MustCompile(`^[0-9a-fA-F]{37}$`).MatchString(address)
}

func sendtx2(c *gin.Context) bool {
	d := c.MustGet("supervisor").(*Supervisor)
	var req message.TxReq
	//请求参数校验
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return false
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return false
	}
	s := ""
	if req.Fee == "" {
		s = req.RandomStr + req.To + req.Value
	} else {
		s = req.RandomStr + req.To + req.Value + req.Fee
	}

	if !VerifySignature(req.PublicKey, s, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: Signature is invalid."})
		return false
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return false
	}
	if !IsEthereumAddress(req.To) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. The format of receiver address is not correct."})
		return false
	}

	bf := new(big.Float)
	bf.SetPrec(512)
	_, success := bf.SetString(req.Value)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Format not correct."})
		return false
	}
	if bf.Signbit() {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Should not be negative."})
		return false
	}
	if bf.Cmp(big.NewFloat(0)) == 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Should not be zero."})
		return false
	}
	if bf.Cmp(big.NewFloat(10000000)) == 1 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Too large."})
		return false
	}
	bffee := new(big.Float)
	bffee.SetPrec(512)
	if req.Fee != "" {
		_, ok := bffee.SetString(req.Fee)
		if !ok {
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. Format not correct."})
			return false
		}
		if bffee.Signbit() {
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. Should not be negative."})
			return false
		}
		if bffee.Cmp(big.NewFloat(0)) == 0 {
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. Should not be zero."})
			return false
		}
		if bffee.Cmp(big.NewFloat(10000000)) == 1 {
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. Too large."})
			return false
		}
	}

	Unit := new(big.Float)
	Unit.SetString(global.Uint)
	bf.Mul(bf, Unit)
	newbf1 := new(big.Float)
	newbf1.SetString("1")
	if bf.Cmp(newbf1) < 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Value is less than 1 wei."})
		return false
	}
	bffee.Mul(bffee, Unit)
	if bffee.Cmp(newbf1) < 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. Fee is less than 1 wei."})
		return false
	}
	if strings.Contains(bf.Text('f', -1), ".") {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. The accuracy of value is exceeded."})
		return false
	}
	if strings.Contains(bffee.Text('f', -1), ".") {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Fee. The accuracy of fee is exceeded."})
		return false
	}

	valueandfee := new(big.Float)
	valueandfee.SetPrec(512)
	valueandfee.Add(bffee, bf)

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.RLock()
	defer d.Lock.RUnlock()

	tx1 := db.DB.Begin()

	from := GetAddress(req.PublicKey)
	var acc1 Account
	if err := tx1.Model(acc1).Where("addr = ?", from).Find(&acc1).Error; err != nil {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From account not exist."})
		return false
	}
	bf2 := new(big.Float)
	bf2.SetPrec(512)
	bf2.SetString(acc1.Value)
	//if bf2.Cmp(bf) == -1 {
	if bf2.Cmp(valueandfee) == -1 {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From account's balance not enough."})
		return false
	}

	var acc2 Account
	if err := tx1.Model(acc2).Where("addr = ?", req.To).Find(&acc2).Error; err != nil {
		//tx1.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. To account not exist."})
		//return false
		acc2.Addr = req.To
		acc2.Version = 0
		acc2.Value = "0"
		if e := tx1.Model(acc2).Create(&acc2).Error; e != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": e.Error()})
			return false
		}
		if e := tx1.Model(acc2).Where("addr = ?", req.To).Find(&acc2).Error; e != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": e.Error()})
			return false
		}
	}

	if acc1.Addr == acc2.Addr {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From and To is required to be different."})
		tx1.Rollback()
		return false
	}

	bf3 := new(big.Float)
	bf3.SetPrec(512)
	bf3.SetString(acc2.Value)

	bff1 := new(big.Float)
	bff1.SetPrec(512)
	bff2 := new(big.Float)
	bff2.SetPrec(512)
	//bff1.Sub(bf2, bf)
	bff1.Sub(bf2, valueandfee)

	bff2.Add(bf3, bf)
	acc1.Value = bff1.Text('f', -1)
	acc2.Value = bff2.Text('f', -1)

	//v1 := acc1.Version
	//v2 := acc2.Version

	count1 := 0
	flag1 := false
	for {
		count1++
		if count1 > 10 {
			break
		}
		res1 := tx1.Model(Account{}).
			Where("id = ? AND version = ?", acc1.Id, acc1.Version).
			Updates(map[string]interface{}{
				"balance": bff1.Text('f', -1),
				"version": acc1.Version + 1,
			})

		if res1.Error != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again."})
			return false
		}
		if res1.RowsAffected > 0 {
			flag1 = true
			break
		}
		time.Sleep(100 * time.Millisecond)
		tx1.Model(acc1).Where("addr = ?", from).Find(&acc1)
		bf2.SetString(acc1.Value)
		//if bf2.Cmp(bf) == -1 {
		if bf2.Cmp(valueandfee) == -1 {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. From account's balance not enough."})
			return false
		}
		//bff1.Sub(bf2, bf)
		bff1.Sub(bf2, valueandfee)
	}
	if !flag1 {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later."})
		return false
	}
	count2 := 0
	flag2 := false
	for {
		count2++
		if count2 > 10 {
			break
		}
		res2 := tx1.Model(Account{}).
			Where("id = ? AND version = ?", acc2.Id, acc2.Version).
			Updates(map[string]interface{}{
				"balance": bff2.Text('f', -1),
				"version": acc2.Version + 1,
			})
		if res2.Error != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again."})
			return false
		}
		if res2.RowsAffected > 0 {
			flag2 = true
			break
		}
		time.Sleep(100 * time.Millisecond)
		tx1.Model(acc2).Where("addr = ?", req.To).Find(&acc2)
		bf3.SetString(acc2.Value)
		bff2 = new(big.Float)
		bff2.Add(bf3, bf)
	}

	if !flag2 {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later."})
		return false
	}

	tt := TX{
		From:      acc1.Addr,
		To:        acc2.Addr,
		Value:     bf.Text('f', -1),
		Timestamp: time.Now(),
		Fee:       bffee.Text('f', -1),
	}
	if e := tx1.Model(tt).Create(&tt).Error; e != nil {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again."})
		return false
	}

	tx1.Commit()

	var aaa big.Int
	aaa.SetString(bf.Text('f', -1), 10)

	//bf.SetInt(&intRound)
	txlist := make([]*core.Transaction, 0)
	tx := core.NewTransaction(from, req.To, &aaa, 123, time.Now())
	roundfee := new(big.Int)
	bffee.Int(roundfee)
	tx.Fee = roundfee
	txlist = append(txlist, tx)

	block := d.CurChain.GenerateBlock2(txlist, d.Root)
	d.CurChain.AddBlock2(block)

	d.TXPool.AddTx2Pool(tx)

	go SubmitToB2E(tx)
	go func() {
		defer func() {
			if err := recover(); err != nil {
				fmt.Println(err)
			}
		}()
		d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: tx.Sender}, partition.Vertex{Addr: tx.Recipient})
	}()

	return true
}

func sendtx(c *gin.Context) {
	if !sendtx2(c) {
		return
	}

	rand.Seed(time.Now().UnixNano())
	randomSeconds := rand.Float64() * 3
	// 转换为毫秒并加上基础3秒
	sleepDuration := 3*time.Second + time.Duration(randomSeconds*1000)*time.Millisecond

	fmt.Println("休眠时间:", sleepDuration)
	time.Sleep(sleepDuration)
	c.JSON(http.StatusOK, gin.H{"message": "Transfer success."})
	//it := message.InjectTxs{
	//	Txs:       txlist,
	//	ToShardID: uint64(utils.Addr2Shard(tx.Sender)),
	//}
	//itByte, err := json.Marshal(it)
	//if err != nil {
	//	log.Panic(err)
	//}
	//send_msg := message.MergeMessage(message.CInject, itByte)
	//go networks.TcpDial(send_msg, d.Ip_nodeTable[it.ToShardID][0])
}
func reward_wallet(c *gin.Context) {
	var req message.RewardReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}

	thedate := req.RandomStr
	if !VerifySignature(req.PublicKey, thedate, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: Signature is invalid."})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	var acc Account
	if err := db.DB.Model(acc).Where("addr = ?", addr).Find(&acc).Error; err != nil {
		acc.Value = "0"
		acc.Addr = addr
		acc.Version = 0
		db.DB.Create(&acc)
	}
	db.DB.Model(acc).Where("addr = ?", addr).Find(&acc)
	bf := new(big.Float)
	bf.SetString(acc.Value)
	reward := new(big.Float)
	reward.SetString("57870370000000")
	bf.Add(bf, reward)
	acc.Value = bf.Text('f', -1)
	acc.Version = acc.Version + 1
	db.DB.Model(acc).Where("id = ?", acc.Id).Update(&acc)
	c.JSON(http.StatusOK, gin.H{"msg": "success"})
}

func queryacc(c *gin.Context) {
	var req message.QueryReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}

	thedate := req.RandomStr + req.UUID
	if !VerifySignature(req.PublicKey, thedate, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: Signature is invalid."})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", req.UUID).Find(&acc1).Error; err != nil {
		r := ReturnAccountState{
			AccountAddr: req.UUID,
			Balance:     "0",
		}
		c.JSON(http.StatusOK, r)
		return
	}
	r := ReturnAccountState{
		AccountAddr: req.UUID,
		Balance:     acc1.Value,
	}
	c.JSON(http.StatusOK, r)
}

func queryacc2(c *gin.Context) {
	var req message.QueryReq2
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", req.UUID).Find(&acc1).Error; err != nil {
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Account not exist."})
		r := ReturnAccountState{
			AccountAddr: req.UUID,
			Balance:     "0",
		}
		c.JSON(http.StatusOK, r)
		return
	}
	r := ReturnAccountState{
		AccountAddr: req.UUID,
		Balance:     acc1.Value,
	}
	c.JSON(http.StatusOK, r)
}
func queryacc3(c *gin.Context) {
	UUID := c.Query("addr")
	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", UUID).Find(&acc1).Error; err != nil {
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Account not exist."})
		r := ReturnAccountState{
			AccountAddr: UUID,
			Balance:     "0",
		}
		c.JSON(http.StatusOK, r)
		return
	}
	Unit := new(big.Float)
	Unit.SetString(global.Uint)
	bf := new(big.Float)
	bf.SetString(acc1.Value)
	bf1 := new(big.Float)
	bf1.Quo(bf, Unit)
	r := ReturnAccountState{
		AccountAddr: UUID,
		Balance:     bf1.Text('f', -1),
	}
	c.JSON(http.StatusOK, r)
}

func queryacc10(c *gin.Context) {
	var req QueryAccReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	res := make([]ReturnAccountState, len(req.Accounts))
	lock := sync.Mutex{}
	wg := sync.WaitGroup{}
	wg.Add(len(req.Accounts))
	for idx, addr1 := range req.Accounts {
		addr := addr1
		go func(i int) {
			defer wg.Done()
			var acc1 Account
			if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
				r := ReturnAccountState{
					AccountAddr: addr,
					Balance:     "0",
				}
				lock.Lock()
				defer lock.Unlock()
				res[i] = r
				return
			}
			Unit := new(big.Float)
			Unit.SetString(global.Uint)
			bf := new(big.Float)
			bf.SetString(acc1.Value)
			bf1 := new(big.Float)
			bf1.Quo(bf, Unit)
			r := ReturnAccountState{
				AccountAddr: addr,
				Balance:     bf1.Text('f', -1),
			}
			lock.Lock()
			defer lock.Unlock()
			res[i] = r
		}(idx)
	}
	wg.Wait()

	c.JSON(http.StatusOK, res)
}
