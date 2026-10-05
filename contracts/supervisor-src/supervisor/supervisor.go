// Supervisor is an abstract role in this simulator that may read txs, generate partition infos,
// and handle history data.

package supervisor

import (
	"blockEmulator/chain"
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/message"
	"blockEmulator/networks"
	"blockEmulator/params"
	"blockEmulator/supervisor/committee"
	"blockEmulator/supervisor/measure"
	"blockEmulator/supervisor/signal"
	"blockEmulator/supervisor/supervisor_log"
	"blockEmulator/vm/state"
	"blockEmulator/vm/trie"
	"blockEmulator/vm/triedb"
	"bufio"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/ethdb"
	"io"
	"log"
	"math/big"
	"net"
	"os"
	"sync"
	"time"
)



type Supervisor struct {
	CurChain *chain.BlockChain
	// basic infos
	IPaddr       string // ip address of this Supervisor
	ChainConfig  *params.ChainConfig
	Ip_nodeTable map[uint64]map[uint64]string

	// tcp control
	listenStop bool
	tcpLn      net.Listener
	tcpLn2     net.Listener
	tcpLock    sync.Mutex
	tcpLock2   sync.Mutex
	// logger module
	sl *supervisor_log.SupervisorLog

	// control components
	Ss *signal.StopSignal // to control the stop message sending

	// supervisor and committee components
	comMod committee.CommitteeModule

	// measure components
	testMeasureMods []measure.MeasureModule

	// diy, add more structures or classes here ...
	Db      ethdb.Database
	Triedb  *triedb.Database
	Statedb *state.CachingDB
	SmallDb       []*ethdb.Database
	SmallTriedb []*triedb.Database
	SmallStatedb []*state.CachingDB
	Root    common.Hash

	TXPool *core.TxPool
	Lock   sync.RWMutex
}

func (d *Supervisor) NewSupervisor(ip string, pcc *params.ChainConfig, committeeMethod string, measureModNames ...string) {
	d.IPaddr = ip
	d.ChainConfig = pcc
	d.Ip_nodeTable = params.IPmap_nodeTable

	d.sl = supervisor_log.NewSupervisorLog()

	d.Ss = signal.NewStopSignal(3 * int(pcc.ShardNums))

	switch committeeMethod {
	case "CLPA_Broker":
		d.comMod = committee.NewCLPACommitteeMod_Broker(d.Ip_nodeTable, d.Ss, d.sl, params.DatasetFile, params.TotalDataSize, params.TxBatchSize, params.ReconfigTimeGap)
	case "CLPA":
		d.comMod = committee.NewCLPACommitteeModule(d.Ip_nodeTable, d.Ss, d.sl, params.DatasetFile, params.TotalDataSize, params.TxBatchSize, params.ReconfigTimeGap)
	case "Broker":
		d.comMod = committee.NewBrokerCommitteeMod(d.Ip_nodeTable, d.Ss, d.sl, params.DatasetFile, params.TotalDataSize, params.TxBatchSize)
	default:
		d.comMod = committee.NewRelayCommitteeModule(d.Ip_nodeTable, d.Ss, d.sl, params.DatasetFile, params.TotalDataSize, params.TxBatchSize)
	}

	d.testMeasureMods = make([]measure.MeasureModule, 0)
	for _, mModName := range measureModNames {
		switch mModName {
		case "TPS_Relay":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestModule_avgTPS_Relay())
		case "TPS_Broker":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestModule_avgTPS_Broker())
		case "TCL_Relay":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestModule_TCL_Relay())
		case "TCL_Broker":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestModule_TCL_Broker())
		case "CrossTxRate_Relay":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestCrossTxRate_Relay())
		case "CrossTxRate_Broker":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestCrossTxRate_Broker())
		case "TxNumberCount_Relay":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestTxNumCount_Relay())
		case "TxNumberCount_Broker":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestTxNumCount_Broker())
		case "Tx_Details":
			d.testMeasureMods = append(d.testMeasureMods, measure.NewTestTxDetail())
		default:
		}
	}
}

// Supervisor received the block information from the leaders, and handle these
// message to measure the performances.
func (d *Supervisor) handleBlockInfos(content []byte) {
	bim := new(message.BlockInfoMsg)
	err := json.Unmarshal(content, bim)
	if err != nil {
		log.Panic()
	}
	// StopSignal check
	if bim.BlockBodyLength == 0 {
		d.Ss.StopGap_Inc()
	} else {
		d.Ss.StopGap_Reset()
	}

	d.comMod.HandleBlockInfo(bim)

	// measure update
	for _, measureMod := range d.testMeasureMods {
		measureMod.UpdateMeasureRecord(bim)
	}
	// add codes here ...
}

// read transactions from dataFile. When the number of data is enough,
// the Supervisor will do re-partition and send partitionMSG and txs to leaders.
func (d *Supervisor) SupervisorTxHandling() {
	d.comMod.MsgSendingControl()
	// TxHandling is end
	for !d.Ss.GapEnough() { // wait all txs to be handled
		time.Sleep(time.Second)
	}
	// send stop message
	stopmsg := message.MergeMessage(message.CStop, []byte("this is a stop message~"))
	d.sl.Slog.Println("Supervisor: now sending cstop message to all nodes")
	for sid := uint64(0); sid < d.ChainConfig.ShardNums; sid++ {
		for nid := uint64(0); nid < d.ChainConfig.Nodes_perShard; nid++ {
			networks.TcpDial(stopmsg, d.Ip_nodeTable[sid][nid])
		}
	}
	// make sure all stop messages are sent.
	time.Sleep(time.Duration(params.Delay+params.JitterRange+3) * time.Millisecond)

	d.sl.Slog.Println("Supervisor: now Closing")
	d.listenStop = true
	d.CloseSupervisor()
}

// handle message. only one message to be handled now
func (d *Supervisor) handleMessage(msg []byte) {
	msgType, content := message.SplitMessage(msg)
	switch msgType {
	case message.CBlockInfo:
		d.handleBlockInfos(content)
		// add codes for more functionality
	default:
		d.comMod.HandleOtherMessage(msg)
		for _, mm := range d.testMeasureMods {
			mm.HandleExtraMessage(msg)
		}
	}
}

var Lock sync.Mutex


func (d *Supervisor) BuildBlockChain() {
	fp := os.Getenv("ATLAS_SUPERVISOR_LEVELDB_DIR")
	if fp == "" {
		fp = "./expTest2"
	}
	exist := true
	if _, err := os.Stat(fp); err != nil {
		exist = false
	}
	var ee error
	d.Db, ee = rawdb.NewLevelDBDatabase(fp, 0, 1, "accountState", false)
	if ee != nil {
		fmt.Println(ee)
		panic(ee)
	}
	triedb2 := triedb.NewDatabase(d.Db, &triedb.Config{
		//Cache:     0,
		Preimages: true,
		IsVerkle:  false,
	})

	d.Triedb = triedb2
	Statedb := state.NewDatabase(triedb2, nil)
	d.Statedb = Statedb

	d.SmallDb = make([]*ethdb.Database, 0)
	d.SmallTriedb = make([]*triedb.Database, 0)
	d.SmallStatedb = make([]*state.CachingDB, 0)

	if !exist {
		statusTrie := trie.NewEmpty(d.Triedb)
		d.Root = statusTrie.Hash()
		con := Config{}
		db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
		con.Value = hex.EncodeToString(d.Root[:])
		db.DB.Model(con).Where("id = ?",con.Id).Update(&con)
		_, err := state.New(d.Root, d.Statedb)
		if err != nil {
			panic(err)
		}
	} else {
		con := Config{}
		db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
		root, _ := hex.DecodeString(con.Value)
		d.Root = common.Hash(root)
		_, err := state.New(d.Root, d.Statedb)
		if err != nil {
			panic(err)
		}
	}

	//var cc Config
	//db.DB.Where("config = ?", "shardid").Find(&cc)
	//shardNum, _ := strconv.Atoi(cc.Value)
	//
	//for i := 0; i < shardNum; i++ {
	//	fp2:="small_tree_shard_"+strconv.Itoa(i)
	//	db2, _ := rawdb.NewLevelDBDatabase(fp2, 0, 1, "accountState", false)
	//	d.SmallDb = append(d.SmallDb, &db2)
	//	triedb2_ := triedb.NewDatabase(db2, &triedb.Config{
	//		//Cache:     0,
	//		Preimages: true,
	//		IsVerkle:  false,
	//	})
	//	d.SmallTriedb = append(d.SmallTriedb, triedb2_)
	//	Statedb2 := state.NewDatabase(triedb2_, nil)
	//	d.SmallStatedb = append(d.SmallStatedb, Statedb2)
	//}


	var superacc []SuperAccount
	db.DB.Model(SuperAccount{}).Find(&superacc)
	txs := make([]*core.Transaction, 0)
	for _, acc := range superacc {
		bf := new(big.Int)
		bf.SetString(acc.Value, 10)
		unit := new(big.Int)
		unit.SetString(global.Uint, 10)
		val := new(big.Int)
		val.Mul(bf, unit)
		transaction := core.NewTransaction("super", acc.Addr, val, 0, time.Now())
		txs = append(txs, transaction)
	}

	d.CurChain, _ = chain.NewBlockChain2(txs, d.Root)

}

func (d *Supervisor) handleClientRequest(con net.Conn) {
	defer con.Close()
	defer func() {
		if err := recover(); err != nil {
			fmt.Println(err)
		}
	}()
	clientReader := bufio.NewReader(con)
	for {
		clientRequest, err := clientReader.ReadBytes('\n')
		switch err {
		case nil:
			d.tcpLock.Lock()
			d.handleMessage(clientRequest)
			d.tcpLock.Unlock()
		case io.EOF:
			log.Println("client closed the connection by terminating the process")
			return
		default:
			log.Printf("error: %v\n", err)
			return
		}
	}
}

func (d *Supervisor) TcpListen() {
	ln, err := net.Listen("tcp", d.IPaddr)
	if err != nil {
		log.Panic(err)
	}
	d.tcpLn = ln
	for {
		conn, err := d.tcpLn.Accept()
		if err != nil {
			return
		}
		go d.handleClientRequest(conn)
	}
}
func (d *Supervisor) TcpListen2() {
	ln, err := net.Listen("tcp", "0.0.0.0:56743")
	if err != nil {
		log.Panic(err)
	}
	d.tcpLn2 = ln
	for {
		conn, err := d.tcpLn2.Accept()
		if err != nil {
			return
		}
		go d.handleClientRequest2(conn)
	}
}

// close Supervisor, and record the data in .csv file
func (d *Supervisor) CloseSupervisor() {
	d.sl.Slog.Println("Closing...")
	for _, measureMod := range d.testMeasureMods {
		d.sl.Slog.Println(measureMod.OutputMetricName())
		d.sl.Slog.Println(measureMod.OutputRecord())
		println()
	}
	networks.CloseAllConnInPool()
	d.tcpLn.Close()
}