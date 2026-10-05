package build

import (
	"blockEmulator/consensus_shard/pbft_all"
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/networks"
	"blockEmulator/params"
	"blockEmulator/supervisor"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log"
	"math/big"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/crypto"
	"github.com/hokaccha/go-prettyjson"
	"github.com/spf13/viper"
)

var WebViper *viper.Viper

type Config struct {
	Id     int64  `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	Config string `gorm:"column:config" json:"config"`
	Value  string `gorm:"column:value" json:"value"`
}

func (*Config) TableName() string {
	return "config"
}
func initConfig(nid, nnm, sid, snm uint64) *params.ChainConfig {
	// Read the contents of ipTable.json
	ipMap := readIpTable("./ipTable.json")
	params.IPmap_nodeTable = ipMap
	params.SupervisorAddr = "127.0.0.1:38800"

	// check the correctness of params
	//if len(ipMap)-1 < int(snm) {
	//	log.Panicf("Input ShardNumber = %d, but only %d shards in ipTable.json.\n", snm, len(ipMap)-1)
	//}
	//for shardID := 0; shardID < len(ipMap)-1; shardID++ {
	//	if len(ipMap[uint64(shardID)]) < int(nnm) {
	//		log.Panicf("Input NodeNumber = %d, but only %d nodes in Shard %d.\n", nnm, len(ipMap[uint64(shardID)]), shardID)
	//	}
	//}

	params.NodesInShard = int(nnm)
	params.ShardNum = int(snm)

	var cc Config
	db.DB.Where("config = ?", "shardid").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)
	params.ShardNum = shardNum

	// init the network layer
	networks.InitNetworkTools()

	pcc := &params.ChainConfig{
		ChainID:        sid,
		NodeID:         nid,
		ShardID:        sid,
		Nodes_perShard: uint64(params.NodesInShard),
		ShardNums:      snm,
		BlockSize:      uint64(params.MaxBlockSize_global),
		BlockInterval:  uint64(params.Block_Interval),
		InjectSpeed:    uint64(params.InjectSpeed),
	}
	return pcc
}
func GetAddress_Old(publickey string) string {
	decodeString, _ := hex.DecodeString(publickey)
	hash := sha256.Sum256(decodeString)
	hash2 := hash[:20]
	address := hex.EncodeToString(hash2)
	return address
}

func GetAddress(publickey string) string {
	bytes, err := hex.DecodeString(publickey)
	if err != nil {
		log.Panicf("GetAddress failed:publickey:%v  err: %v", publickey, err)
		return "error"
	}
	publicKey, err := crypto.UnmarshalPubkey(bytes)
	if err != nil {
		log.Panicf("GetAddress failed:publickey:%v  err: %v", publickey, err)
		return "error"
	}
	address := crypto.PubkeyToAddress(*publicKey)
	addr := strings.ToLower(address.String())
	if len(addr) > 2 && addr[:2] == "0x" {
		addr = addr[2:]
	}
	return addr
}

func BuildSupervisor(nnm, snm uint64) {
	InitConfig()
	db.InitDB()

	//var ac supervisor.Account
	//tx := db.DB.Begin()
	//tx.Model(ac).Where("id = ? ",1).Find(&ac)
	//fmt.Println(ac)
	//time.Sleep(time.Second *5)
	//
	//ac.Value ="123"
	//res1 := tx.Model(supervisor.Account{}).
	//	Where("id = ? AND version = ?", ac.Id, ac.Version).
	//	Updates(map[string]interface{}{
	//		"balance":  ac.Value,
	//		"version":  ac.Version + 1,
	//	})
	//
	//if res1.Error != nil {
	//	tx.Rollback()
	//	fmt.Println("Failed1. Please try again.")
	//	return
	//}
	//
	//// 检查是否成功更新了记录
	//if res1.RowsAffected == 0 {
	//	tx.Rollback()
	//	fmt.Println("Failed2. Please try again.")
	//	return
	//}
	//
	//tx.Commit()
	//return

	var CreationConfig Config
	if e := db.DB.Model(CreationConfig).Where("config = ?", "Creation").Find(&CreationConfig).Error; e != nil {
		milli := time.Now().UnixMilli()
		formatInt := strconv.FormatInt(milli, 10)
		CreationConfig.Value = formatInt
		CreationConfig.Config = "Creation"
		db.DB.Model(CreationConfig).Create(&CreationConfig)
	}

	//发行超级账户
	var superacc []supervisor.SuperAccount
	db.DB.Model(supervisor.SuperAccount{}).Find(&superacc)
	for _, acc := range superacc {
		acc.Addr = GetAddress_Old(acc.PublicKey)
		db.DB.Model(acc).Where("id = ?", acc.Id).Update(&acc)
		bf := new(big.Float)
		bf.SetPrec(512)
		bf.SetString(acc.Value)
		if bf.Cmp(big.NewFloat(100000001)) == 1 {
			global.SuperAcc = acc.Addr
		}
		var account supervisor.Account
		if e := db.DB.Model(account).Find(&account, "addr = ?", acc.Addr).Error; e != nil {
			account.Addr = acc.Addr
			//account.Value = acc.Value

			num := new(big.Float)
			num.SetString(acc.Value)
			num2 := new(big.Float)
			num2.SetString(global.Uint)
			num3 := new(big.Float)
			num3.Mul(num, num2)
			fmt.Println(num3)
			account.Value = num3.Text('f', -1)

			account.Version = 0
			db.DB.Model(account).Create(&account)

			//bigInt:=new (big.Int)
			//bigInt.SetString(account.Value,10)
			//var have uint256.Int
			//have.SetFromBig(bigInt)
			//fmt.Println("have:",have)
			//fmt.Println("have.string:",have.String())
			//fmt.Println("bigInt.Text(10):",bigInt.Text(10))
		}

		var loc supervisor.Location
		if e := db.DB.Model(loc).Find(&loc, "addr = ?", acc.Addr).Error; e != nil {
			loc.Addr = acc.Addr
			loc.Location = 0
			db.DB.Model(loc).Create(&loc)
		}

		var problem supervisor.Problem
		if err := db.DB.Model(problem).Find(&problem, "pk = ?", acc.Addr).Error; err != nil {
			problem.PublicKey = acc.Addr
			db.DB.Model(problem).Create(&problem)
		}

	}

	methodID := params.ConsensusMethod
	var measureMod []string
	if methodID == 0 || methodID == 2 {
		measureMod = params.MeasureBrokerMod
	} else {
		measureMod = params.MeasureRelayMod
	}
	measureMod = append(measureMod, "Tx_Details")

	lsn := new(supervisor.Supervisor)
	lsn.NewSupervisor(params.SupervisorAddr, initConfig(123, nnm, 123, snm), params.CommitteeMethod[methodID], measureMod...)
	lsn.BuildBlockChain()
	lsn.TXPool = core.NewTxPool()
	go lsn.RunHTTP()
	go lsn.DeleteDead()
	go lsn.DeleteDead_senior()
	go lsn.Record()
	go lsn.Doonce()
	go lsn.OpenShard()
	go lsn.OpenShard_senior()
	go lsn.RecordId()
	go lsn.RecordId_senior()
	//go lsn.Backupdatabase()
	go lsn.ScheduleB2E()
	go lsn.PackTXs()
	//go lsn.Reconfig()

	go lsn.TcpListen()
	go lsn.TcpListen2()
	//strs:=[]string{
	//	"30770395b9ca70e5999d9c5170730fe5dc3323ab",
	//	"429b840376ed2c3d22e69ae042fcbe749a92015f",
	//	"9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1",
	//	"bf01bae34bd9d2482f4f3f7fa6cfb680f0548c83",
	//	"cbb9edb109e585909745c67cc854ec3176371c42",
	//	"f60a415657cba6cbd10011dbcd71c133db390985",
	//	}
	//for _, s := range strs {
	//	supervisor.Withdrawbroker2(s)
	//}
	go lsn.RunEthRpc()
	time.Sleep(5000 * time.Millisecond)
	for {
		time.Sleep(time.Second)
	}
	//lsn.SupervisorTxHandling()
}

func InitCMViper() (*viper.Viper, error) {
	cmViper := viper.New()
	cmViper.SetConfigFile("./config/config.yml")
	if err := cmViper.ReadInConfig(); err != nil {
		return nil, err
	}
	return cmViper, nil
}
func InitConfig() {
	var err error
	if WebViper, err = InitCMViper(); err != nil {
		log.Fatal("Load config failed, ", err)
	}
	if err = WebViper.Unmarshal(&db.GlobalConfig); err != nil {
		log.Fatal("Unmarshal config failed, ", err)
	}

	json, err := prettyjson.Marshal(db.GlobalConfig)
	if err != nil {
		log.Fatalf("marshal alarm config failed, %s", err.Error())
	}
	fmt.Println(string(json))
}

func BuildNewPbftNode(nid, nnm, sid, snm uint64) {
	methodID := params.ConsensusMethod
	worker := pbft_all.NewPbftNode(sid, nid, initConfig(nid, nnm, sid, snm), params.CommitteeMethod[methodID])
	go worker.TcpListen()
	worker.Propose()
}
