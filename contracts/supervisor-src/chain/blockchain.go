// Here the blockchain structrue is defined
// each node in this system will maintain a blockchain object.

package chain

import (
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/params"
	"blockEmulator/storage"
	"blockEmulator/utils"
	"blockEmulator/vm"
	"blockEmulator/vm/state"
	"blockEmulator/vm/tracing"
	"bytes"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"sync/atomic"
	"unicode"

	"github.com/ethereum/go-ethereum/common"
	"github.com/holiman/uint256"
	"github.com/jinzhu/gorm"

	"log"
	"math/big"
	"sync"
	"time"

	"github.com/bits-and-blooms/bitset"

	"blockEmulator/vm/trie"
	"blockEmulator/vm/triedb"

	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/ethdb"
)

type BlockChain struct {
	db           ethdb.Database      // the leveldb database to store in the disk, for status trie
	triedb       *triedb.Database    // the trie database which helps to store the status trie
	ChainConfig  *params.ChainConfig // the chain configuration, which can help to identify the chain
	CurrentBlock *core.Block         // the top block in this blockchain
	Storage      *storage.Storage    // Storage is the bolt-db to store the blocks
	Txpool       *core.TxPool        // the transaction pool
	PartitionMap map[string]uint64   // the partition map which is defined by some algorithm can help account parition
	pmlock       sync.RWMutex
}

func stringToFixedByteArray(s string) [20]byte {
	var b [20]byte
	copy(b[:], []byte(s)) // 将s的字节复制到b的前len(s)个位置
	// 如果需要，可以在这里手动填充剩余的字节
	// 例如，填充为0
	for i := len(s); i < 20; i++ {
		b[i] = 0
	}
	return b
}

type ChainContext interface {
	// Engine retrieves the chain's consensus engine.
	//Engine() consensus.Engine

	// GetHeader returns the header corresponding to the hash/number argument pair.
	GetHeader(common.Hash, uint64) *core.BlockHeader
}

func (bc *BlockChain) GetHeader(hash common.Hash, number uint64) *core.BlockHeader {
	block, err := bc.Storage.GetBlock(hash[:])
	if err != nil {
		return nil
	}
	return block.Header
}
func CanTransfer(db vm.StateDB, addr common.Address, amount *uint256.Int) bool {
	return db.GetBalance(addr).Cmp(amount) >= 0
}

func Transfer(db vm.StateDB, sender, recipient common.Address, amount *uint256.Int) {
	db.SubBalance(sender, amount, tracing.BalanceChangeTransfer)
	db.AddBalance(recipient, amount, tracing.BalanceChangeTransfer)
}
func GetHashFn(ref *core.BlockHeader, chain *BlockChain) func(n uint64) common.Hash {
	// Cache will initially contain [refHash.parent],
	// Then fill up with [refHash.p, refHash.pp, refHash.ppp, ...]
	//var cache []common.Hash

	return func(n uint64) common.Hash {

		if n >= ref.Number {
			return common.Hash{}
		}
		blockHash, _ := chain.Storage.GetNewestBlockHash()
		for {
			block, err := chain.Storage.GetBlock(blockHash)
			if err != nil {
				return common.Hash{}
			}
			if block.Header.Number == n {
				return common.Hash(block.Hash)
			}
			blockHash = block.Header.ParentBlockHash
		}

		//if ref.Number <= n {
		//	// This situation can happen if we're doing tracing and using
		//	// block overrides.
		//	return common.Hash{}
		//}
		// If there's no hash cache yet, make one
		//if len(cache) == 0 {
		//	cache = append(cache, ref.ParentHash)
		//}
		//if idx := ref.Number - n - 1; idx < uint64(len(cache)) {
		//	return cache[idx]
		//}
		// No luck in the cache, but we can start iterating from the last element we already know
		//lastKnownHash := cache[len(cache)-1]
		//lastKnownNumber := ref.Number - uint64(len(cache))

		//lastKnownHash := ref.ParentHash
		//lastKnownNumber := n
		//
		//for {
		//	header := chain.GetHeader(lastKnownHash, lastKnownNumber)
		//	if header == nil {
		//		break
		//	}
		//	//cache = append(cache, header.ParentHash)
		//	lastKnownHash = header.ParentHash
		//	lastKnownNumber = header.Number - 1
		//	if n == lastKnownNumber {
		//		return lastKnownHash
		//	}
		//}

		return common.Hash{}
	}
}

func NewEVMBlockContext(header *core.BlockHeader, bc *BlockChain, gaslimit uint64) vm.BlockContext {
	var (
		beneficiary common.Address
		baseFee     *big.Int
		blobBaseFee *big.Int
		random      *common.Hash
	)

	// If we don't have an explicit author (i.e. not mining), extract from the header
	//if author == nil {
	//	beneficiary, _ = chain.Engine().Author(header) // Ignore error, we're past header validation
	//} else {
	//	beneficiary = *author
	//}
	//if header.BaseFee != nil {
	//	baseFee = new(big.Int).Set(header.BaseFee)
	//}
	//if header.ExcessBlobGas != nil {
	//	blobBaseFee = eip4844.CalcBlobFee(*header.ExcessBlobGas)
	//}
	//if header.Difficulty.Sign() == 0 {
	//	random = &header.MixDigest
	//}

	return vm.BlockContext{
		CanTransfer: CanTransfer,
		Transfer:    Transfer,
		GetHash:     GetHashFn(header, bc),
		Coinbase:    beneficiary,
		//BlockNumber: new(big.Int).Set(uint64tobigintptr(header.Number)),
		BlockNumber: new(big.Int).SetUint64(header.Number),
		Time:        uint64(header.Time.UnixMilli()),
		//Time:        uint64(time.Now().UnixMilli()),
		//Difficulty:  new(big.Int).Set(header.Difficulty),
		BaseFee:     baseFee,
		BlobBaseFee: blobBaseFee,
		GasLimit:    gaslimit,
		Random:      random,
	}
}
func uint64tobigintptr(u uint64) *big.Int {
	var bigNum big.Int

	bigNum.SetUint64(u)
	return &bigNum
}
func NewEVMTxContext(msg *core.Message) vm.TxContext {
	ctx := vm.TxContext{
		Origin:     msg.From,
		GasPrice:   new(big.Int).Set(msg.GasPrice),
		BlobHashes: msg.BlobHashes,
	}
	if msg.BlobGasFeeCap != nil {
		ctx.BlobFeeCap = new(big.Int).Set(msg.BlobGasFeeCap)
	}
	return ctx
}
func ApplyTransactionWithEVM(msg *core.Message, gp *vm.GasPool, statedb *state.StateDB, evm *vm.EVM, UUID string, TX *gorm.DB, est bool, call bool) (result *vm.ExecutionResult, err error) {
	//if evm.Config.Tracer != nil && evm.Config.Tracer.OnTxStart != nil {
	//	evm.Config.Tracer.OnTxStart(evm.GetVMContext(), tx, msg.From)
	//	if evm.Config.Tracer.OnTxEnd != nil {
	//		defer func() {
	//			evm.Config.Tracer.OnTxEnd(receipt, err)
	//		}()
	//	}
	//}
	// Create a new context to be used in the EVM environment.

	txContext := NewEVMTxContext(msg)
	evm.Reset(txContext, statedb)

	// Apply the transaction to the current state (included in the env).
	result, err = vm.ApplyMessage(evm, msg, gp, UUID, TX, est, call)
	if err != nil {
		log.Printf("result, err = vm.ApplyMessage(evm, msg, gp,UUID)错误:%v \n", err.Error())
		return nil, err
	}
	if result.Err != nil && result.Err.Error() != "" {
		//fmt.Println("result, err = vm.ApplyMessage(evm, msg, gp,UUID)错误:" + result.Err.Error())
		return result, result.Err
	}
	//statedb.IntermediateRoot(true)

	// Update the state with pending changes.
	//var root []byte
	//if config.IsByzantium(blockNumber) {
	//	statedb.Finalise(true)
	//} else {
	//	root = statedb.IntermediateRoot(config.IsEIP158(blockNumber)).Bytes()
	//}
	//*usedGas += result.UsedGas

	return result, nil
}

type Config struct {
	Id     int64  `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	Config string `gorm:"column:config" json:"config"`
	Value  string `gorm:"column:value" json:"value"`
}

func isVisible(r rune) bool {
	// 判断字符是否为字母、数字或常见标点符号
	return unicode.IsLetter(r) || unicode.IsDigit(r) || unicode.IsPunct(r) || unicode.IsSpace(r)
}

func filterVisibleChars(input string) string {
	var result []rune
	for _, r := range input {
		if isVisible(r) {
			result = append(result, r)
		}
	}
	return string(result)
}
func (*Config) TableName() string {
	return "config"
}

var blockNum atomic.Int64

func ExeTx(tx *core.Transaction, statedb *state.StateDB, blockHeader *core.BlockHeader, bc *BlockChain, idx int, gp *vm.GasPool, UUID string, TX *gorm.DB, est bool, call bool, IP string) (common.Hash, uint64, error, [][]string) {
	s1, _ := hex.DecodeString(tx.Sender)

	from := common.Address(s1)

	s2, _ := hex.DecodeString(tx.Recipient)
	var s3 [20]byte
	var To common.Address
	if tx.Recipient == "" {
		s3 = stringToFixedByteArray("")
		To = s3
	} else {
		To = common.Address(s2)
	}
	conf := Config{}
	db.DB.Model(conf).Where("config = ?", "gasprice").Find(&conf)

	gasp, _ := new(big.Int).SetString(conf.Value, 10)
	msg := &core.Message{
		Nonce:     tx.Nonce, //目前是按交易递增的，实际是按sender递增的
		GasLimit:  gp.Gas(),
		GasPrice:  gasp,
		GasFeeCap: new(big.Int).SetInt64(1),
		GasTipCap: new(big.Int).SetInt64(1),
		//To:               copyAddressPtr(tx.To),
		To:               To,
		Value:            new(big.Int).Set(tx.Value),
		Data:             tx.Data,
		AccessList:       nil,
		SkipNonceChecks:  false,
		SkipFromEOACheck: false,
		BlobHashes:       nil,
		BlobGasFeeCap:    nil,
		From:             from,
	}

	decodedinput := string(tx.Data)
	visibleStr := ""
	if len(decodedinput) > 0 {
		visibleStr = filterVisibleChars(decodedinput)
	}

	fmt.Println("gasprice为:", msg.GasPrice)
	fmt.Println("gaslimit为:", msg.GasLimit)

	var snap = statedb.Snapshot()

	//fmt.Println("NewEVMBlockContext")
	blockContext := NewEVMBlockContext(blockHeader, bc, msg.GasLimit)

	blockContext.Coinbase = common.Address{}

	//txContext := NewEVMTxContext(msg)
	//fmt.Println("NewEVM")

	vmenv := vm.NewEVM(blockContext, vm.TxContext{}, statedb, nil, vm.Config{})
	vmenv.TX = TX
	//fmt.Println("SetTxContext")
	txhash, _ := hex.DecodeString(UUID)
	statedb.SetTxContext(common.Hash(txhash), idx)

	//fmt.Println("ApplyTransactionWithEVM")
	log.Printf("ApplyTransactionWithEVM msg: %+v \n", msg)

	now := time.Now()
	res, err := ApplyTransactionWithEVM(msg, gp, statedb, vmenv, UUID, TX, est, call)
	txs := vmenv.TXs
	milliseconds := time.Since(now).Milliseconds()
	var zeroAddr common.Address

	if est {
		TX.Rollback()
		statedb.RevertToSnapshot(snap)
		if res != nil {
			return common.Hash{}, res.UsedGas, nil, txs
		} else {
			return common.Hash{}, 0, nil, txs
		}
	}
	//gasp,_:=new(big.Int).SetString(global.GasPrice,10)
	blockNumber := blockNum.Add(1)
	if res != nil {

		if res.Err != nil {
			TX.Rollback()

			invoke := db.ContractInvoke{
				Success:         0,
				Value:           tx.Value.Text(16),
				Res:             res.Err.Error(),
				TransactionHash: UUID,
                Nonce: tx.Nonce,
				ContractAddress: "",
				GasUsed:         strconv.FormatUint(res.UsedGas, 16),
				From:            tx.Sender,
				To:              tx.Recipient,
				Input:           hex.EncodeToString(tx.Data),
				GasPrice:        gasp.Text(16),
				Time:            int(milliseconds),
				BlockNumber:     int(blockNumber),
				Timestamp:       now,
				DecodedInput:    visibleStr,
				IP:              IP,
			}
			if call {
				invoke.Type = "eth_call"
			} else {
				invoke.Type = "eth_sendtransaction"
			}
			db.DB.Model(invoke).Create(&invoke)
		} else {

			updated := TX.Table("account_nonce").Where("addr = ? AND nonce = ?",tx.Sender,tx.Nonce).Update("nonce",tx.Nonce+1)
            if updated.Error != nil || updated.RowsAffected != 1 {
                TX.Rollback(); statedb.RevertToSnapshot(snap)
                return common.Hash{},0,errors.New("account nonce update failed"),nil
            }

			if res.ContractAddr != zeroAddr {
				fmt.Println("UUID为" + UUID + ",执行结果为" + hex.EncodeToString(res.ContractAddr[:]))
				invoke := db.ContractInvoke{
					Success:         1,
					Value:           tx.Value.Text(16),
					Res:             hex.EncodeToString(res.ReturnData),
					TransactionHash: UUID,
                Nonce: tx.Nonce,
					ContractAddress: hex.EncodeToString(res.ContractAddr[:]),
					GasUsed:         strconv.FormatUint(res.UsedGas, 16),
					From:            tx.Sender,
					To:              tx.Recipient,
					Input:           hex.EncodeToString(tx.Data),
					GasPrice:        gasp.Text(16),
					Time:            int(milliseconds),
					BlockNumber:     int(blockNumber),
					Timestamp:       now,
					DecodedInput:    visibleStr,
					IP:              IP,
				}
				if call {
					invoke.Type = "eth_call"
				} else {
					invoke.Type = "eth_sendtransaction"
				}
				if saveError := TX.Model(invoke).Create(&invoke).Error; saveError != nil { TX.Rollback(); statedb.RevertToSnapshot(snap); return common.Hash{},0,saveError,nil }
				//bc.Storage.AddContractRes(UUID, res.ContractAddr[:])
			} else {
				invoke := db.ContractInvoke{
					Success:         1,
					Value:           tx.Value.Text(16),
					Res:             hex.EncodeToString(res.ReturnData),
					TransactionHash: UUID,
                Nonce: tx.Nonce,
					//ContractAddress: hex.EncodeToString(res.ContractAddr[:]),
					ContractAddress: "",
					GasUsed:         strconv.FormatUint(res.UsedGas, 16),
					From:            tx.Sender,
					To:              tx.Recipient,
					Input:           hex.EncodeToString(tx.Data),
					GasPrice:        gasp.Text(16),
					Time:            int(milliseconds),
					BlockNumber:     int(blockNumber),
					Timestamp:       now,
					DecodedInput:    visibleStr,
					IP:              IP,
				}
				if call {
					invoke.Type = "eth_call"
				} else {
					invoke.Type = "eth_sendtransaction"
				}
				fmt.Println("UUID为" + UUID + ",执行结果为" + hex.EncodeToString(res.ReturnData))
				if saveError := TX.Model(invoke).Create(&invoke).Error; saveError != nil { TX.Rollback(); statedb.RevertToSnapshot(snap); return common.Hash{},0,saveError,nil }
				//bc.Storage.AddContractRes(UUID, res.ReturnData)
			}
		}
	} else {
		TX.Rollback()
		//bc.Storage.AddContractRes(UUID, []byte(err.Error()))
		invoke := db.ContractInvoke{
			Success:         0,
			Value:           tx.Value.Text(16),
			Res:             err.Error(),
			TransactionHash: UUID,
                Nonce: tx.Nonce,
			ContractAddress: "",
			//GasUsed: strconv.FormatUint(res.UsedGas, 16),
			GasUsed:      strconv.FormatUint(0, 16),
			From:         tx.Sender,
			To:           tx.Recipient,
			Input:        hex.EncodeToString(tx.Data),
			GasPrice:     gasp.Text(16),
			Time:         int(milliseconds),
			BlockNumber:  int(blockNumber),
			Timestamp:    now,
			DecodedInput: visibleStr,
			IP:           IP,
		}
		if call {
			invoke.Type = "eth_call"
		} else {
			invoke.Type = "eth_sendtransaction"
		}
		db.DB.Model(invoke).Create(&invoke)
	}

 if res != nil && res.Err == nil && err == nil { if commitError := TX.Commit().Error; commitError != nil { statedb.RevertToSnapshot(snap); return common.Hash{},0,commitError,nil } }

	//bc.Storage.DataBase.Sync()
	if err != nil {
		fmt.Println("exetx回滚，UUID为" + UUID + ",error为" + err.Error())
		statedb.RevertToSnapshot(snap)
		//TODO
		//gp = new(vm.GasPool).AddGas(blockHeader.GasLimit)
		//tx.Log = nil
		//log.Panic(err)
	}
	if res != nil && res.Err != nil {
		fmt.Println(res.Err)
	}

	if res != nil {
		fmt.Println("使用的gas:", res.UsedGas)
		fmt.Println("退还的gas:", res.RefundedGas)
	}

	//statedb.IntermediateRoot(false)
	hash, _ := statedb.Commit(0, false)

	if res != nil {
		if res.Err != nil {
			return hash, res.UsedGas, res.Err, txs
		} else {
			return hash, res.UsedGas, nil, txs
		}

	}
	return hash, 0, err, txs

	//m := new(message.TxInfo)
	//m.TxHash = tx.TxHash
	//if res != nil && res.Err == nil {
	//	m.IsSuccess = true
	//} else {
	//	m.IsSuccess = false
	//}
	//
	//m.GasPrice = tx.GasPrice.Uint64()
	//if res != nil {
	//	m.GasUsed = res.UsedGas
	//
	//	//m.ExecuteResult = res.ReturnData
	//}
	//m.GasLimit = tx.Gas
	//m.IsContract = true
	//m.ExecuteTime = time.Now()
	//
	//m.From = tx.From
	//m.To = tx.To
	//m.Input = tx.Data
	//m.Value = tx.Value
	//m.UUID = tx.UUID
	//
	//if res != nil {
	//	if res.ContractAddr != zeroAddr {
	//		m.Res = res.ContractAddr[:]
	//	} else {
	//		m.Res = res.ReturnData
	//	}
	//} else {
	//	m.Res = []byte(err.Error())
	//}
	//
	//b, _ := json.Marshal(m)
	//m1 := message.MergeMessage(message.CTxInfo, b)
	//go networks.TcpDial(m1, params.IPmap_nodeTable[params.DeciderShard][0])

}

//statedb.IntermediateRoot(true)

// Get the transaction root, this root can be used to check the transactions
func GetTxTreeRoot(txs []*core.Transaction) []byte {
	// use a memory trie database to do this, instead of disk database
	triedb := triedb.NewDatabase(rawdb.NewMemoryDatabase(), nil)

	transactionTree := trie.NewEmpty(triedb)
	for _, tx := range txs {
		transactionTree.Update(tx.TxHash, tx.Encode())
	}
	return transactionTree.Hash().Bytes()
}

// Get bloom filter
func GetBloomFilter(txs []*core.Transaction) *bitset.BitSet {
	bs := bitset.New(2048)
	for _, tx := range txs {
		bs.Set(utils.ModBytes(tx.TxHash, 2048))
	}
	return bs
}

// Write Partition Map
func (bc *BlockChain) Update_PartitionMap(key string, val uint64) {
	bc.pmlock.Lock()
	defer bc.pmlock.Unlock()
	bc.PartitionMap[key] = val
}

// Get parition (if not exist, return default)
func (bc *BlockChain) Get_PartitionMap(key string) uint64 {
	bc.pmlock.RLock()
	defer bc.pmlock.RUnlock()
	if _, ok := bc.PartitionMap[key]; !ok {
		return uint64(utils.Addr2Shard(key))
	}
	return bc.PartitionMap[key]
}

// Send a transaction to the pool (need to decide which pool should be sended)
func (bc *BlockChain) SendTx2Pool(txs []*core.Transaction) {
	bc.Txpool.AddTxs2Pool(txs)
}

// handle transactions and modify the status trie
func (bc *BlockChain) GetUpdateStatusTrie(txs []*core.Transaction) common.Hash {
	fmt.Printf("The len of txs is %d\n", len(txs))
	// the empty block (length of txs is 0) condition
	if len(txs) == 0 {
		return common.BytesToHash(bc.CurrentBlock.Header.StateRoot)
	}
	// build trie from the triedb (in disk)
	st, err := trie.New(trie.TrieID(common.BytesToHash(bc.CurrentBlock.Header.StateRoot)), bc.triedb)
	if err != nil {
		log.Panic(err)
	}
	cnt := 0
	// handle transactions, the signature check is ignored here
	for i, tx := range txs {
		// fmt.Printf("tx %d: %s, %s\n", i, tx.Sender, tx.Recipient)
		// senderIn := false
		if !tx.Relayed && (bc.Get_PartitionMap(tx.Sender) == bc.ChainConfig.ShardID || tx.HasBroker) {
			// senderIn = true
			// fmt.Printf("the sender %s is in this shard %d, \n", tx.Sender, bc.ChainConfig.ShardID)
			// modify local accountstate
			s_state_enc, _ := st.Get([]byte(tx.Sender))
			var s_state *core.AccountState
			if s_state_enc == nil {
				// fmt.Println("missing account SENDER, now adding account")
				ib := new(big.Int)
				ib.Add(ib, params.Init_Balance)
				s_state = &core.AccountState{
					Nonce:   uint64(i),
					Balance: ib,
				}
			} else {
				s_state = core.DecodeAS(s_state_enc)
			}
			s_balance := s_state.Balance
			if s_balance.Cmp(tx.Value) == -1 {
				fmt.Printf("the balance is less than the transfer amount\n")
				continue
			}
			s_state.Deduct(tx.Value)
			st.Update([]byte(tx.Sender), s_state.Encode())
			cnt++
		}
		// recipientIn := false
		if bc.Get_PartitionMap(tx.Recipient) == bc.ChainConfig.ShardID || tx.HasBroker {
			// fmt.Printf("the recipient %s is in this shard %d, \n", tx.Recipient, bc.ChainConfig.ShardID)
			// recipientIn = true
			// modify local state
			r_state_enc, _ := st.Get([]byte(tx.Recipient))
			var r_state *core.AccountState
			if r_state_enc == nil {
				// fmt.Println("missing account RECIPIENT, now adding account")
				ib := new(big.Int)
				ib.Add(ib, params.Init_Balance)
				r_state = &core.AccountState{
					Nonce:   uint64(i),
					Balance: ib,
				}
			} else {
				r_state = core.DecodeAS(r_state_enc)
			}
			r_state.Deposit(tx.Value)
			st.Update([]byte(tx.Recipient), r_state.Encode())
			cnt++
		}
	}
	// commit the memory trie to the database in the disk
	if cnt == 0 {
		return common.BytesToHash(bc.CurrentBlock.Header.StateRoot)
	}
	rt, ns := st.Commit(false)
	// if `ns` is nil, the `err = bc.triedb.Update(trie.NewWithNodeSet(ns))` will report an error.
	if ns != nil {
		//err = bc.triedb.Update(trie.NewWithNodeSet(ns))
		//if err != nil {
		//	log.Panic()
		//}
		err = bc.triedb.Commit(rt, false)
		if err != nil {
			log.Panic(err)
		}
	}
	fmt.Println("modified account number is ", cnt)
	return rt
}
func (bc *BlockChain) GenerateBlock2(txs []*core.Transaction, rt common.Hash) *core.Block {
	bh := &core.BlockHeader{
		ParentBlockHash: bc.CurrentBlock.Hash,
		Number:          bc.CurrentBlock.Header.Number + 1,
		Time:            time.Now(),
	}

	bh.StateRoot = rt.Bytes()
	bh.TxRoot = GetTxTreeRoot(txs)
	bh.Bloom = *GetBloomFilter(txs)
	bh.Miner = 0
	b := core.NewBlock(bh, txs)

	b.Hash = b.Header.Hash()
	return b
}
func (bc *BlockChain) GenerateBlockHeader() *core.BlockHeader {
	bh := &core.BlockHeader{
		ParentBlockHash: bc.CurrentBlock.Hash,
		Number:          bc.CurrentBlock.Header.Number + 1,
		Time:            time.Now(),
	}
	bh.Miner = 0
	return bh
}
func (bc *BlockChain) GenerateBlock3(bh *core.BlockHeader, txs []*core.Transaction, rt common.Hash) *core.Block {
	bh.StateRoot = rt.Bytes()
	bh.TxRoot = GetTxTreeRoot(txs)
	bh.Bloom = *GetBloomFilter(txs)
	b := core.NewBlock(bh, txs)
	b.Hash = b.Header.Hash()
	return b
}

// generate (mine) a block, this function return a block
func (bc *BlockChain) GenerateBlock(miner int32) *core.Block {
	var txs []*core.Transaction
	// pack the transactions from the txpool
	if params.UseBlocksizeInBytes == 1 {
		txs = bc.Txpool.PackTxsWithBytes(params.BlocksizeInBytes)
	} else {
		txs = bc.Txpool.PackTxs(bc.ChainConfig.BlockSize)
	}

	bh := &core.BlockHeader{
		ParentBlockHash: bc.CurrentBlock.Hash,
		Number:          bc.CurrentBlock.Header.Number + 1,
		Time:            time.Now(),
	}
	// handle transactions to build root
	rt := bc.GetUpdateStatusTrie(txs)

	bh.StateRoot = rt.Bytes()
	bh.TxRoot = GetTxTreeRoot(txs)
	bh.Bloom = *GetBloomFilter(txs)
	bh.Miner = miner
	b := core.NewBlock(bh, txs)

	b.Hash = b.Header.Hash()
	return b
}

func (bc *BlockChain) NewGenisisBlock2(txs []*core.Transaction, hash common.Hash) *core.Block {
	bh := &core.BlockHeader{
		Number: 0,
		Time:   time.Now().UTC(),
	}
	bh.StateRoot = hash.Bytes()
	bh.TxRoot = GetTxTreeRoot(txs)
	bh.Bloom = *GetBloomFilter(txs)
	b := core.NewBlock(bh, txs)
	b.Hash = b.Header.Hash()
	return b
}

// new a genisis block, this func will be invoked only once for a blockchain object
func (bc *BlockChain) NewGenisisBlock() *core.Block {
	body := make([]*core.Transaction, 0)
	bh := &core.BlockHeader{
		Number: 0,
		Time:   time.Now().UTC(),
	}
	statusTrie := trie.NewEmpty(bc.triedb)

	// build a new trie database by db
	//triedb := trie.NewDatabaseWithConfig(bc.db, &trie.Config{
	//	Cache:     0,
	//	Preimages: true,
	//})
	//bc.triedb = triedb
	//statusTrie := trie.NewEmpty(triedb)
	bh.StateRoot = statusTrie.Hash().Bytes()
	bh.TxRoot = GetTxTreeRoot(body)
	bh.Bloom = *GetBloomFilter(body)
	b := core.NewBlock(bh, body)
	b.Hash = b.Header.Hash()
	return b
}

// add the genisis block in a blockchain
func (bc *BlockChain) AddGenisisBlock(gb *core.Block) {
	bc.Storage.AddBlock(gb)
	newestHash, err := bc.Storage.GetNewestBlockHash()
	if err != nil {
		log.Panic()
	}
	curb, err := bc.Storage.GetBlock(newestHash)
	if err != nil {
		log.Panic()
	}
	bc.CurrentBlock = curb
}
func (bc *BlockChain) AddBlock2(b *core.Block) {
	//if b.Header.Number!=0 && b.Header.Number != bc.CurrentBlock.Header.Number+1 {
	//	fmt.Println("the block height is not correct")
	//	return
	//}
	//if b.Header.Number!=0 && !bytes.Equal(b.Header.ParentBlockHash, bc.CurrentBlock.Hash) {
	//	fmt.Println("err parent block hash")
	//	return
	//}
	bc.CurrentBlock = b
	bc.Storage.AddBlock(b)
}

// add a block
func (bc *BlockChain) AddBlock(b *core.Block) {
	if b.Header.Number != bc.CurrentBlock.Header.Number+1 {
		fmt.Println("the block height is not correct")
		return
	}

	if !bytes.Equal(b.Header.ParentBlockHash, bc.CurrentBlock.Hash) {
		fmt.Println("err parent block hash")
		return
	}

	// if the treeRoot is existed in the node, the transactions is no need to be handled again
	_, err := trie.New(trie.TrieID(common.BytesToHash(b.Header.StateRoot)), bc.triedb)
	if err != nil {
		rt := bc.GetUpdateStatusTrie(b.Body)
		fmt.Println(bc.CurrentBlock.Header.Number+1, "the root = ", rt.Bytes())
	}
	bc.CurrentBlock = b
	bc.Storage.AddBlock(b)
}
func NewBlockChain2(txs []*core.Transaction, hash common.Hash) (*BlockChain, error) {
	fmt.Println("Generating a new blockchain")
	chainDBfp := params.DatabaseWrite_path + "chainDB/supervisor2"
	bc := &BlockChain{
		Storage: storage.NewStorage2(chainDBfp),
	}
	curHash, err := bc.Storage.GetNewestBlockHash()
	if err != nil {
		fmt.Println("There is no existed blockchain in the database. ")
		if err.Error() == "cannot find the newest block hash" {
			genisisBlock := bc.NewGenisisBlock2(txs, hash)
			bc.AddBlock2(genisisBlock)
			fmt.Println("New genesis block")
			return bc, nil
		}
		log.Panic()
	}

	// there is a blockchain in the storage
	fmt.Println("Existing blockchain found")
	curb, err := bc.Storage.GetBlock(curHash)
	if err != nil {
		log.Panic()
	}

	bc.CurrentBlock = curb
	fmt.Println("Generated a new blockchain successfully")
	return bc, nil
}

// new a blockchain.
// the ChainConfig is pre-defined to identify the blockchain; the db is the status trie database in disk
func NewBlockChain(cc *params.ChainConfig, db ethdb.Database) (*BlockChain, error) {
	fmt.Println("Generating a new blockchain", db)
	chainDBfp := params.DatabaseWrite_path + fmt.Sprintf("chainDB/S%d_N%d", cc.ShardID, cc.NodeID)
	bc := &BlockChain{
		db:           db,
		ChainConfig:  cc,
		Txpool:       core.NewTxPool(),
		Storage:      storage.NewStorage(chainDBfp, cc),
		PartitionMap: make(map[string]uint64),
	}
	curHash, err := bc.Storage.GetNewestBlockHash()
	if err != nil {
		fmt.Println("There is no existed blockchain in the database. ")
		// if the Storage bolt database cannot find the newest blockhash,
		// it means the blockchain should be built in height = 0
		if err.Error() == "cannot find the newest block hash" {
			genisisBlock := bc.NewGenisisBlock()
			bc.AddGenisisBlock(genisisBlock)
			fmt.Println("New genesis block")
			return bc, nil
		}
		log.Panic()
	}

	// there is a blockchain in the storage
	fmt.Println("Existing blockchain found")
	curb, err := bc.Storage.GetBlock(curHash)
	if err != nil {
		log.Panic()
	}

	bc.CurrentBlock = curb
	//triedb := trie.NewDatabaseWithConfig(db, &trie.Config{
	//	Cache:     0,
	//	Preimages: true,
	//})
	//bc.triedb = triedb
	// check the existence of the trie database
	//_, err = trie.New(trie.TrieID(common.BytesToHash(curb.Header.StateRoot)), triedb)
	//if err != nil {
	//	log.Panic()
	//}
	fmt.Println("The status trie can be built")
	fmt.Println("Generated a new blockchain successfully")
	return bc, nil
}

// check a block is valid or not in this blockchain config
func (bc *BlockChain) IsValidBlock(b *core.Block) error {
	if string(b.Header.ParentBlockHash) != string(bc.CurrentBlock.Hash) {
		fmt.Println("the parentblock hash is not equal to the current block hash")
		return errors.New("the parentblock hash is not equal to the current block hash")
	} else if string(GetTxTreeRoot(b.Body)) != string(b.Header.TxRoot) {
		fmt.Println("the transaction root is wrong")
		return errors.New("the transaction root is wrong")
	}
	return nil
}

// add accounts
func (bc *BlockChain) AddAccounts(ac []string, as []*core.AccountState, miner int32) {
	fmt.Printf("The len of accounts is %d, now adding the accounts\n", len(ac))

	bh := &core.BlockHeader{
		ParentBlockHash: bc.CurrentBlock.Hash,
		Number:          bc.CurrentBlock.Header.Number + 1,
		Time:            time.Time{},
	}
	// handle transactions to build root
	rt := bc.CurrentBlock.Header.StateRoot
	if len(ac) != 0 {
		st, err := trie.New(trie.TrieID(common.BytesToHash(bc.CurrentBlock.Header.StateRoot)), bc.triedb)
		if err != nil {
			log.Panic(err)
		}
		for i, addr := range ac {
			if bc.Get_PartitionMap(addr) == bc.ChainConfig.ShardID {
				ib := new(big.Int)
				ib.Add(ib, as[i].Balance)
				new_state := &core.AccountState{
					Balance: ib,
					Nonce:   as[i].Nonce,
				}
				st.Update([]byte(addr), new_state.Encode())
			}
		}

		//rrt, ns := st.Commit(false)

		// if `ns` is nil, the `err = bc.triedb.Update(trie.NewWithNodeSet(ns))` will report an error.
		//if ns != nil {
		//	err = bc.triedb.Update(trie.NewWithNodeSet(ns))
		//	if err != nil {
		//		log.Panic(err)
		//	}
		//	err = bc.triedb.Commit(rrt, false)
		//	if err != nil {
		//		log.Panic(err)
		//	}
		//	rt = rrt.Bytes()
		//}
	}

	emptyTxs := make([]*core.Transaction, 0)
	bh.StateRoot = rt
	bh.TxRoot = GetTxTreeRoot(emptyTxs)
	bh.Bloom = *GetBloomFilter(emptyTxs)
	bh.Miner = 0
	b := core.NewBlock(bh, emptyTxs)
	b.Hash = b.Header.Hash()

	bc.CurrentBlock = b
	bc.Storage.AddBlock(b)
}

// fetch accounts
func (bc *BlockChain) FetchAccounts(addrs []string) []*core.AccountState {
	res := make([]*core.AccountState, 0)
	st, err := trie.New(trie.TrieID(common.BytesToHash(bc.CurrentBlock.Header.StateRoot)), bc.triedb)
	if err != nil {
		log.Panic(err)
	}
	for _, addr := range addrs {
		asenc, _ := st.Get([]byte(addr))
		var state_a *core.AccountState
		if asenc == nil {
			ib := new(big.Int)
			ib.Add(ib, params.Init_Balance)
			state_a = &core.AccountState{
				Nonce:   uint64(0),
				Balance: ib,
			}
		} else {
			state_a = core.DecodeAS(asenc)
		}
		res = append(res, state_a)
	}
	return res
}

// close a blockChain, close the database inferfaces
func (bc *BlockChain) CloseBlockChain() {
	//bc.Storage.DataBase.Close()
	//bc.triedb.Commit(bc.CurrentBlock.Header.Root, false)
	//bc.db.Close()
}

// print the details of a blockchain
func (bc *BlockChain) PrintBlockChain() string {
	vals := []interface{}{
		bc.CurrentBlock.Header.Number,
		bc.CurrentBlock.Hash,
		bc.CurrentBlock.Header.StateRoot,
		bc.CurrentBlock.Header.Time,
		bc.triedb,
		// len(bc.Txpool.RelayPool[1]),
	}
	res := fmt.Sprintf("%v\n", vals)
	fmt.Println(res)
	return res
}
