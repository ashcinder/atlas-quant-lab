package supervisor

import (
	"blockEmulator/chain"
	"blockEmulator/core"
	"blockEmulator/global"
	"blockEmulator/partition"
	"blockEmulator/supervisor/committee"
	"blockEmulator/utils"
	"blockEmulator/vm"
	"blockEmulator/vm/state"
	"crypto/elliptic"
	"crypto/sha256"
	"log"
	"math/big"
	"math/rand"
	"time"

	"blockEmulator/db"
	"encoding/hex"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/ethereum/go-ethereum/core/types"

	"github.com/ethereum/go-ethereum/common"
	"github.com/gin-gonic/gin"
)

func eth_call(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req CallContractReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.To + req.Data + req.Value + req.RandomStr

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
	IP := c.ClientIP()

	Lock.Lock()
	defer Lock.Unlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "error, account not found"})
		return
	}

	if req.To != "" && strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	} else {

	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 16)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid value"})
		return
	}
	inp := []byte{}
	if strings.HasPrefix(req.Data, "0x") {
		inp, _ = hex.DecodeString(req.Data[2:])
	}
	//tx1 := db.DB.Begin()
	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)
	var (
		gp = new(vm.GasPool).AddGas(2000000)
		//statedb, _ = state.New(d.Root, d.Statedb)
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)

	//statedb.TX = tx1
	tx := core.NewTransaction2(addr, req.To, val, 0, time.Now(), inp)
	tx.Data = inp
	randomBytes := make([]byte, 32)
	_, _ = rand.Read(randomBytes)
	hexString := hex.EncodeToString(randomBytes)

	tx1 := db.DB.Begin()

	hash, _, _, _ := chain.ExeTx(tx, statedb, d.CurChain.CurrentBlock.Header, d.CurChain, 0, gp, hexString, tx1, false, true, IP)

	//d.Root = hash
	d.Root = hash
	err2 := d.Triedb.Commit(hash, false)
	if err2 != nil {
		fmt.Println("d.Triedb.Commit(hash, false):", err2)
	}
	conf := Config{}
	db.DB.Model(conf).Where("config = ?", "roothash").Find(&conf)
	conf.Value = hex.EncodeToString(hash[:])
	db.DB.Model(conf).Where("id = ?", conf.Id).Update(&conf)

	txs := make([]*core.Transaction, 0)
	txs = append(txs, tx)
	block := d.CurChain.GenerateBlock2(txs, hash)
	d.CurChain.AddBlock2(block)

	var invoke2 db.ContractInvoke
	if db.DB.Model(invoke2).Order("id DESC").First(&invoke2).Error == nil {
		invoke2.BlockHash = hex.EncodeToString(block.Hash)
		invoke2.BlockNumber = int(block.Header.Number)
		db.DB.Model(invoke2).Where("id = ?", invoke2.Id).Update(&invoke2)
	}

	invoke := db.ContractInvoke{}
	db.DB.Model(invoke).Where("hash = ?", hexString).Find(&invoke)

	//tx1.Commit()
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	response.Result = "0x" + invoke.Res
	fmt.Println("respose:", response)
	c.JSON(200, response)
}
func eth_sendTransaction(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req SendContractReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.To + req.Data + req.Value + req.Gas + req.RandomStr

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
	IP := c.ClientIP()

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.RLock()
	defer d.Lock.RUnlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "error, account not found"})
		return
	}
	if strings.HasPrefix(req.Gas, "0x") {
		req.Gas = req.Gas[2:]
	}

	gas, err := strconv.ParseUint(req.Gas, 16, 64)
	if err != nil {
		fmt.Println(err)
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid gas"})
		return
	}

	if req.To != "" && strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	} else {

	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 16)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid value"})
		return
	}
	inp := []byte{}
	if strings.HasPrefix(req.Data, "0x") {
		inp, _ = hex.DecodeString(req.Data[2:])
	}

	str := string(inp)
	if len(str) > 0 {
		visibleStr := filterVisibleChars(str)
		if len(visibleStr) > 0 {
			if !checkSensitive(visibleStr) {
				response := RpcResponse{
					Jsonrpc: "2.0",
					Id:      1,
				}
				response.Error = map[string]interface{}{
					"code":    -32000,
					"message": "请勿输入有害、违法等不良信息",
				}
				c.JSON(200, response)
				return
			}
		}
	}

	conf1 := Config{}
	db.DB.Model(conf1).Where("config = ?", "gasprice").Find(&conf1)

	gasp, _ := new(big.Int).SetString(conf1.Value, 10)
	mgval := new(big.Int).SetUint64(gas)
	mgval.Mul(mgval, gasp)
	bigInt := new(big.Int)
	bigInt.SetString(acc1.Value, 10)

	if bigInt.Cmp(mgval) < 0 {
		response := RpcResponse{
			Jsonrpc: "2.0",
			Id:      1,
		}
		response.Error = map[string]interface{}{
			"code":    -32000,
			"message": "not have enough token",
		}
		c.JSON(200, response)
		return
	}

	//tx1 := db.DB.Begin()

	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)

	var (
		gp = new(vm.GasPool).AddGas(gas)
		//statedb, _ = state.New(d.Root, d.Statedb)
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)
	//statedb.TX = tx1
	tx := core.NewTransaction2(addr, req.To, val, 0, time.Now(), inp)
	tx.Data = inp
	tx.SC = true
	randomBytes := make([]byte, 32)
	_, _ = rand.Read(randomBytes)
	hexString := hex.EncodeToString(randomBytes)

	tx1 := db.DB.Begin()
	blockHeader := d.CurChain.GenerateBlockHeader()

	hash, _, eee, clpatxs := chain.ExeTx(tx, statedb, blockHeader, d.CurChain, 0, gp, hexString, tx1, false, false, IP)
	if clpatxs != nil && len(clpatxs) > 0 {
		for _, arr := range clpatxs {
			go func() {
				defer func() {
					if err1 := recover(); err1 != nil {
						fmt.Println(err1)
					}
				}()
				d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: arr[0]}, partition.Vertex{Addr: arr[1]})
			}()
			//d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: arr[0]}, partition.Vertex{Addr:  arr[1]})
		}
	}
	d.Root = hash
	err2 := d.Triedb.Commit(hash, false)
	if err2 != nil {
		fmt.Println("d.Triedb.Commit(hash, false):", err2)
	}

	conf := Config{}
	db.DB.Model(conf).Where("config = ?", "roothash").Find(&conf)
	conf.Value = hex.EncodeToString(hash[:])
	db.DB.Model(conf).Where("id = ?", conf.Id).Update(&conf)

	txs := make([]*core.Transaction, 0)
	txs = append(txs, tx)

	block := d.CurChain.GenerateBlock3(blockHeader, txs, hash)
	//block := d.CurChain.GenerateBlock2(txs, hash)
	d.CurChain.AddBlock2(block)

	d.TXPool.AddTx2Pool(tx)

	if eee == nil {
		if len(statedb.Logs()) > 0 {
			fun := func(logs []*types.Log) {
				for _, log := range logs {
					var l Log
					l.BlockHash = "0x" + hex.EncodeToString(block.Hash)
					l.BlockNumber = "0x" + fmt.Sprintf("%x", block.Header.Number)
					l.Address = "0x" + hex.EncodeToString(log.Address[:])
					l.TxHash = "0x" + hex.EncodeToString(log.TxHash[:])
					l.Data = "0x" + hex.EncodeToString(log.Data)
					l.Index = "0x" + fmt.Sprintf("%x", log.Index)
					l.TxIndex = "0x" + fmt.Sprintf("%x", log.TxIndex)
					topics := log.Topics
					topicstr := make([]string, 0)
					for _, topic := range topics {
						topicstr = append(topicstr, "0x"+hex.EncodeToString(topic[:]))
					}
					l.Topics = strings.Join(topicstr, ",")
					if log.Removed {
						l.Removed = 1
					} else {
						l.Removed = 0
					}
					db.DB.Model(l).Create(&l)
				}
			}
			fun(statedb.Logs())
		}

	}

	var invoke db.ContractInvoke
	if db.DB.Model(invoke).Order("id DESC").First(&invoke).Error == nil {
		invoke.BlockHash = hex.EncodeToString(block.Hash)
		invoke.BlockNumber = int(block.Header.Number)
		db.DB.Model(invoke).Where("id = ?", invoke.Id).Update(&invoke)
	}

	if eee != nil {
		response := RpcResponse{
			Jsonrpc: "2.0",
			Id:      1,
		}
		response.Error = map[string]interface{}{
			"code":    -32000,
			"message": eee.Error(),
		}
		c.JSON(200, response)
		return
	}

	//tx1.Commit()
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	response.Result = "0x" + hexString
	fmt.Println("respose:", response)
	c.JSON(200, response)
}

func eth_sendRawTransaction(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req SendContractReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	//thedata := req.To + req.Data + req.Value + req.Gas + req.RandomStr
	//if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
	//	return
	//}

	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	log.Printf("eth_sendRawTransaction, req: %+v \n", req)
	addr := req.PublicKey
	if addr[:2] == "0x" {
		addr = addr[2:]
	}
	if !checkaccexist2(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}
	IP := c.ClientIP()

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.RLock()
	defer d.Lock.RUnlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "error, account not found"})
		return
	}
	if strings.HasPrefix(req.Gas, "0x") {
		req.Gas = req.Gas[2:]
	}

	gas, err := strconv.ParseUint(req.Gas, 16, 64)
	if err != nil {
		fmt.Println(err)
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid gas"})
		return
	}

	if req.To != "" && strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	} else {

	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 10)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid value"})
		return
	}
	inp := []byte{}
	if strings.HasPrefix(req.Data, "0x") {
		inp, _ = hex.DecodeString(req.Data[2:])
	}

	str := string(inp)
	if len(str) > 0 {
		visibleStr := filterVisibleChars(str)
		if len(visibleStr) > 0 {
			if !checkSensitive(visibleStr) {
				response := RpcResponse{
					Jsonrpc: "2.0",
					Id:      1,
				}
				response.Error = map[string]interface{}{
					"code":    -32000,
					"message": "请勿输入有害、违法等不良信息",
				}
				c.JSON(200, response)
				return
			}
		}
	}

	conf1 := Config{}
	db.DB.Model(conf1).Where("config = ?", "gasprice").Find(&conf1)

	gasp, _ := new(big.Int).SetString(conf1.Value, 10)
	mgval := new(big.Int).SetUint64(gas)
	mgval.Mul(mgval, gasp)
	bigInt := new(big.Int)
	bigInt.SetString(acc1.Value, 10)

	if bigInt.Cmp(mgval) < 0 {
		response := RpcResponse{
			Jsonrpc: "2.0",
			Id:      1,
		}
		response.Error = map[string]interface{}{
			"code":    -32000,
			"message": "not have enough token",
		}
		c.JSON(200, response)
		return
	}

	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)

	var (
		gp = new(vm.GasPool).AddGas(gas)
		//statedb, _ = state.New(d.Root, d.Statedb)
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)
	log.Printf("statedb : %x\n", statedb)

	//statedb.TX = tx1
	tx := core.NewTransaction2(addr, req.To, val, 0, time.Now(), inp)
	tx.Data = inp
	tx.SC = true
	randomBytes := make([]byte, 32)
	_, _ = rand.Read(randomBytes)
	hexString := hex.EncodeToString(randomBytes)

	tx1 := db.DB.Begin()
	blockHeader := d.CurChain.GenerateBlockHeader()
	log.Printf("run tx : %+v \n", tx)
	hash, _, eee, clpatxs := chain.ExeTx(tx, statedb, blockHeader, d.CurChain, 0, gp, hexString, tx1, false, false, IP)
	if clpatxs != nil && len(clpatxs) > 0 {
		for _, arr := range clpatxs {
			go func() {
				defer func() {
					if err1 := recover(); err1 != nil {
						fmt.Println(err1)
					}
				}()
				d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: arr[0]}, partition.Vertex{Addr: arr[1]})
			}()
			//d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: arr[0]}, partition.Vertex{Addr:  arr[1]})
		}
	}
	d.Root = hash
	err2 := d.Triedb.Commit(hash, false)
	if err2 != nil {
		fmt.Println("d.Triedb.Commit(hash, false):", err2)
	}

	conf := Config{}
	db.DB.Model(conf).Where("config = ?", "roothash").Find(&conf)
	conf.Value = hex.EncodeToString(hash[:])
	db.DB.Model(conf).Where("id = ?", conf.Id).Update(&conf)

	txs := make([]*core.Transaction, 0)
	txs = append(txs, tx)

	block := d.CurChain.GenerateBlock3(blockHeader, txs, hash)
	//block := d.CurChain.GenerateBlock2(txs, hash)
	d.CurChain.AddBlock2(block)

	d.TXPool.AddTx2Pool(tx)

	if eee == nil {
		if len(statedb.Logs()) > 0 {
			fun := func(logs []*types.Log) {
				for _, log := range logs {
					var l Log
					l.BlockHash = "0x" + hex.EncodeToString(block.Hash)
					l.BlockNumber = "0x" + fmt.Sprintf("%x", block.Header.Number)
					l.Address = "0x" + hex.EncodeToString(log.Address[:])
					l.TxHash = "0x" + hex.EncodeToString(log.TxHash[:])
					l.Data = "0x" + hex.EncodeToString(log.Data)
					l.Index = "0x" + fmt.Sprintf("%x", log.Index)
					l.TxIndex = "0x" + fmt.Sprintf("%x", log.TxIndex)
					topics := log.Topics
					topicstr := make([]string, 0)
					for _, topic := range topics {
						topicstr = append(topicstr, "0x"+hex.EncodeToString(topic[:]))
					}
					l.Topics = strings.Join(topicstr, ",")
					if log.Removed {
						l.Removed = 1
					} else {
						l.Removed = 0
					}
					db.DB.Model(l).Create(&l)
				}
			}
			fun(statedb.Logs())
		}

	}

	var invoke db.ContractInvoke
	if db.DB.Model(invoke).Order("id DESC").First(&invoke).Error == nil {
		invoke.BlockHash = hex.EncodeToString(block.Hash)
		invoke.BlockNumber = int(block.Header.Number)
		db.DB.Model(invoke).Where("id = ?", invoke.Id).Update(&invoke)
	}

	if eee != nil {
		response := RpcResponse{
			Jsonrpc: "2.0",
			Id:      1,
		}
		response.Error = map[string]interface{}{
			"code":    -32000,
			"message": eee.Error(),
		}
		c.JSON(200, response)
		return
	}

	//tx1.Commit()
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	response.Result = "0x" + hexString
	log.Println("response:", response)
	c.JSON(200, response)
}
func eth_getTransactionByHash(c *gin.Context) {
	var req GetTXByHashReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.UUID
	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}

	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	//addr := GetAddress(req.PublicKey)
	//var p Problem
	//if err := db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
	//	c.JSON(http.StatusOK, gin.H{"error": "publickey not exist"})
	//	return
	//}

	var contractInvoke db.ContractInvoke
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
		Result:  nil,
	}
	if db.DB.Model(&contractInvoke).Where("hash = ?", req.UUID).Find(&contractInvoke).Error != nil {
		c.JSON(200, response)
		return
	}
	if len(contractInvoke.To) < 1 {
		contractInvoke.To = "0000000000000000000000000000000000000000"
	}
	r1 := &TransactionResult{
		BlockHash:        "0x" + contractInvoke.BlockHash,
		BlockNumber:      "0x" + fmt.Sprintf("%x", contractInvoke.BlockNumber),
		From:             "0x" + contractInvoke.From,
		Gas:              "0x" + contractInvoke.GasUsed,
		GasPrice:         "0x" + contractInvoke.GasPrice,
		Hash:             "0x" + contractInvoke.TransactionHash,
		Input:            "0x" + contractInvoke.Input,
		Nonce:            "0x" + fmt.Sprintf("%x", contractInvoke.BlockNumber),
		To:               "0x" + contractInvoke.To,
		TransactionIndex: "0x0",
		Value:            "0x" + contractInvoke.Value,
		V:                "0x25",
		R:                "0x1b5e176d927f8e9ab405058b2d2457392da3e20f328b16ddabcebc33eaac5fea",
		S:                "0x4ba69724e8f69de52f0125ad8b3c5c2cef33019bac3249e2c0a2192766d1721c",
	}
	log.Printf("eth_getTransactionByHash : %+v", r1)
	response.Result = r1
	c.JSON(200, response)
}

func eth_estimateGas(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req EstContractReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.To + req.Data + req.Value + req.RandomStr
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
		c.JSON(http.StatusOK, gin.H{"error": "publickey not exist"})
		return
	}
	IP := c.ClientIP()

	Lock.Lock()
	defer Lock.Unlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "error, account not found"})
		return
	}
	if strings.HasPrefix(req.Gas, "0x") {
		req.Gas = req.Gas[2:]
	}

	//gas, err := strconv.ParseUint(req.Gas , 16, 64)
	//if err != nil {
	//	fmt.Println(err)
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid gas"})
	//	return
	//}
	if strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 16)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid value"})
		return
	}
	inp := []byte{}
	if strings.HasPrefix(req.Value, "0x") {
		inp, _ = hex.DecodeString(req.Data[2:])
	}
	//tx1 := db.DB.Begin()
	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)
	gas := 1000000000
	var (
		gp = new(vm.GasPool).AddGas(uint64(gas))
		//statedb, _ = state.New(d.Root, d.Statedb)
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)
	//statedb.TX = tx1
	tx := core.NewTransaction(addr, req.To, val, 0, time.Now())
	tx.Data = inp
	randomBytes := make([]byte, 32)
	_, _ = rand.Read(randomBytes)
	hexString := hex.EncodeToString(randomBytes)

	tx1 := db.DB.Begin()

	_, gasused, _, _ := chain.ExeTx(tx, statedb, d.CurChain.CurrentBlock.Header, d.CurChain, 0, gp, hexString, tx1, true, false, IP)

	//d.Root = hash
	//
	//conf:=Config{}
	//db.DB.Model(conf).Where("config = ?","roothash").Find(&conf)
	//conf.Value = hex.EncodeToString(hash[:])
	//db.DB.Model(conf).Update(&conf)

	gasused *= 10

	//tx1.Commit()
	response := RpcResponse{
		Jsonrpc: "2.0",
		//Id:      request.Id,
	}
	response.Result = "0x" + fmt.Sprintf("%x", gasused)
	c.JSON(200, response)
}

func eth_getTransactionCount(c *gin.Context) {
	var req TransactionCountReq
	if err := c.ShouldBind(&req); err != nil {
		log.Printf("eth_getTransactionCount err : %v \n", err)
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	log.Printf("eth_getTransactionCount req : %v \n", req)
	var count int64
	err := db.DB.Model(&TX{}).Where("`from` = ?", req.From[2:]).Count(&count).Error
	if err != nil {
		log.Printf("eth_getTransactionCount err : %v \n", err)
	}
	response := RpcResponse{
		Jsonrpc: "2.0",
	}
	log.Printf("eth_getTransactionCount count: %v \n", count)
	response.Result = fmt.Sprintf("%x", count)
	c.JSON(200, response)
}

func eth_getTransactionReceipt(c *gin.Context) {
	var req GetTransactionReceiptReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.UUID
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

	u := req.UUID
	invoke := db.ContractInvoke{}
	response := RpcResponse{
		Jsonrpc: "2.0",
	}
	if db.DB.Model(invoke).Where("hash = ?", u).First(&invoke).Error != nil {
		response.Result = "0x"
		c.JSON(200, response)
		return
	}
	bytes2 := make([]byte, 32)
	rand.Read(bytes2)

	mm := TxRec{
		From:              "0x" + invoke.From,
		BlockHash:         "0x" + invoke.BlockHash,
		BlockNumber:       "0x" + fmt.Sprintf("%x", invoke.BlockNumber),
		TransactionHash:   "0x" + invoke.TransactionHash,
		TransactionIndex:  "0x0",
		GasUsed:           "0x" + invoke.GasUsed,
		Status:            "",
		Logs:              nil,
		LogsBloom:         "0x" + hex.EncodeToString(bytes2),
		CumulativeGasUsed: "0x" + invoke.GasUsed,
		EffectiveGasPrice: "0x" + invoke.GasPrice,
		Type:              "0x2",
	}
	var logs []Log
	db.DB.Model(Log{}).Where("txhash = ?", "0x"+u).Find(&logs)
	if len(logs) > 0 {
		var ll []map[string]interface{}
		for _, log1 := range logs {
			split := strings.Split(log1.Topics, ",")
			l := map[string]interface{}{
				"logIndex":         log1.Index,
				"transactionIndex": log1.TxIndex,
				"transactionHash":  log1.TxHash,
				"blockHash":        log1.BlockHash,
				"blockNumber":      log1.BlockNumber,
				"address":          log1.Address,
				"data":             log1.Data,
				"removed":          log1.Removed == 1,
				"topics":           split,
			}
			ll = append(ll, l)
		}
		mm.Logs = ll
	} else {
		mm.Logs = make([]map[string]interface{}, 0)
	}

	if invoke.To != "" {
		mm.To = "0x" + invoke.To
	}
	if invoke.ContractAddress != "" {
		mm.ContractAddress = "0x" + invoke.ContractAddress
	}

	if invoke.Success == 1 {
		mm.Status = "0x1"
	} else {
		mm.Status = "0x0"
	}
	response.Result = mm
	c.JSON(200, response)
}

func eth_blockNumber(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req GetBlockNumReq
	if err := c.ShouldBindJSON(&req); err != nil {
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

	//addr := GetAddress(req.PublicKey)
	//var p Problem
	//if err := db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
	//	c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
	//	return
	//}
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	response.Result = "0x" + fmt.Sprintf("%x", d.CurChain.CurrentBlock.Header.Number)
	c.JSON(200, response)
}
func eth_getBlockByNumber(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req GetBlockByNumReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.UUID
	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	//addr := GetAddress(req.PublicKey)
	//var p Problem
	//if err := db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
	//	c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
	//	return
	//}
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	u := req.UUID
	binfo := new(BlockInfo)
	if u == "latest" {
		currentBlock := d.CurChain.CurrentBlock
		binfo.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		binfo.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		binfo.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		binfo.Difficulty = "0x18eba2"
		binfo.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		binfo.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		binfo.TotalDifficulty = "0xba39edb8"
		binfo.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		binfo.GasLimit = "0x1388"
		binfo.GasUsed = "0x0"
		binfo.Transactions = make([]interface{}, 0)
		binfo.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		binfo.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		binfo.Uncles = []string{}
		binfo.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		binfo.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		binfo.Nonce = "0x18c9465ff80c4e57"
	} else {
		number, err := strconv.ParseUint(u, 16, 64)
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"error": err.Error()})
			return
		}
		currentBlock := d.CurChain.CurrentBlock
		blockHash, _ := d.CurChain.Storage.GetNewestBlockHash()
		for {
			block, err := d.CurChain.Storage.GetBlock(blockHash)
			if err != nil {
				c.JSON(http.StatusOK, gin.H{"error": err.Error()})
				return
			}
			if block.Header.Number == number {
				currentBlock = block
				break
			}
			blockHash = block.Header.ParentBlockHash
		}
		binfo.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		binfo.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		binfo.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		binfo.Difficulty = "0x18eba2"
		binfo.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		binfo.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		binfo.TotalDifficulty = "0xba39edb8"
		binfo.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		binfo.GasLimit = "0x1388"
		binfo.GasUsed = "0x0"
		binfo.Transactions = make([]interface{}, 0)
		binfo.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		binfo.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		binfo.Uncles = []string{}
		binfo.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		binfo.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		binfo.Nonce = "0x18c9465ff80c4e57"
	}

	response.Result = binfo
	c.JSON(200, response)
}

func eth_getBlockByHash(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req GetBlockByNumReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	log.Printf("eth_getBlockByHash: req : %v\n", req)
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.UUID
	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}

	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	u := req.UUID
	binfo := new(BlockInfo)
	if u == "latest" {
		currentBlock := d.CurChain.CurrentBlock
		binfo.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		binfo.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		binfo.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		binfo.Difficulty = "0x18eba2"
		binfo.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		binfo.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		binfo.TotalDifficulty = "0xba39edb8"
		binfo.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		binfo.GasLimit = "0x1388"
		binfo.GasUsed = "0x0"
		binfo.Transactions = make([]interface{}, 0)
		binfo.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		binfo.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		binfo.Uncles = []string{}
		binfo.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		binfo.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		binfo.Nonce = "0x18c9465ff80c4e57"
	} else {
		if u[:2] == "0x" {
			u = u[2:]
		}
		hash, err := hex.DecodeString(u)
		if err != nil {
			return
		}
		currentBlock, err := d.CurChain.Storage.GetBlock(hash)
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"error": err.Error()})
			return
		}

		binfo.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		binfo.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		binfo.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		binfo.Difficulty = "0x18eba2"
		binfo.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		binfo.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		binfo.TotalDifficulty = "0xba39edb8"
		binfo.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		binfo.GasLimit = "0x1388"
		binfo.GasUsed = "0x0"
		binfo.Transactions = make([]interface{}, 0)
		binfo.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		binfo.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		binfo.Uncles = []string{}
		binfo.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		binfo.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		binfo.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		binfo.Nonce = "0x18c9465ff80c4e57"
	}
	response.Result = binfo
	c.JSON(200, response)
}

func eth_getCode(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req GetCodeReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.UUID
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

	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)
	statedb, _ := state.New(common.Hash(root), d.Statedb)
	addr2, ee := hex.DecodeString(req.UUID)
	response := RpcResponse{
		Jsonrpc: "2.0",
		Id:      1,
	}
	if ee != nil {
		c.JSON(200, response)
		return
	}
	fmt.Println("eth_getCode, addr", common.Address(addr2))
	code := statedb.GetCode(common.Address(addr2))
	response.Result = "0x" + hex.EncodeToString(code)
	c.JSON(200, response)
}

func getcontractinvoke(c *gin.Context) {
	count := c.Query("count")
	if count == "" {
		count = "100"
	}
	count_, _ := strconv.Atoi(count)
	var invoke []db.ContractInvoke
	db.DB.Model(&db.ContractInvoke{}).Order("id desc").Limit(count_).Find(&invoke)
	c.JSON(http.StatusOK, invoke)
}

func getwls(c *gin.Context) {
	var res []PendingNode2
	db.DB.Model(&PendingNode2{}).Find(&res)
	c.JSON(http.StatusOK, res)
}

func getwlj(c *gin.Context) {
	var res []PendingNode
	db.DB.Model(&PendingNode{}).Find(&res)
	c.JSON(http.StatusOK, res)
}

func getOldAccount(c *gin.Context) {
	privKey := c.Query("privKey")
	if len(privKey) == 0 {
		c.JSON(http.StatusOK, gin.H{"error": "privKey is null"})
		return
	}

	publicKey := getPublicKeyFromPrivateKeyOld(privKey)
	address := getAddressFromPublicKeyOld(publicKey)
	kv := make(map[string]string)

	kv["address"] = address
	kv["balance"] = "0"
	var account Account
	if err := db.DB.Model(account).Where("addr = ?", address).Find(&account).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Request failed, please try again."})
		return
	} else {
		val, err1 := utils.WeiToEthTrim(account.Value)
		if err1 != nil {
			c.JSON(http.StatusOK, gin.H{"error": "Request failed, please try again."})
			return
		}
		kv["balance"] = val
		if len(address) > 2 && address[:2] != "0x" {
			kv["address"] = "0x" + address
		}
	}
	c.JSON(http.StatusOK, kv)
}

func getPublicKeyFromPrivateKeyOld(privKey string) string {
	privateKey := new(big.Int)
	privateKey.SetString(privKey, 10)
	x, y := elliptic.P256().ScalarBaseMult(privateKey.Bytes())
	pubKeyBytes := elliptic.MarshalCompressed(elliptic.P256(), x, y)
	return hex.EncodeToString(pubKeyBytes)
}

func getAddressFromPublicKeyOld(publicKey string) string {
	decodeString, _ := hex.DecodeString(publicKey)
	hash := sha256.Sum256(decodeString)
	hash2 := hash[:20]
	address := hex.EncodeToString(hash2)
	return address
}

type TransferToNewReq struct {
	From   string `json:"from"`
	To     string `json:"to"`
	PrivK  string `json:"privK"`
	Amount string `json:"amount"`
}

func transferToNewAccount(c *gin.Context) {
	var req TransferToNewReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	log.Printf("transferToNewAccount:%+v", req)
	d := c.MustGet("supervisor").(*Supervisor)
	if req.PrivK == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: PublicKey is null"})
		return
	}

	publicKey := getPublicKeyFromPrivateKeyOld(req.PrivK)
	address := getAddressFromPublicKeyOld(publicKey)
	from := req.From
	if len(address) < 2 || len(from) < 2 || len(req.To) < 2 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid address format!"})
	}
	if address[:2] == "0x" {
		address = address[2:]
	}
	if from[:2] == "0x" {
		from = from[2:]
	}
	if req.To[:2] == "0x" {
		req.To = req.To[2:]
	}

	if address != from {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. The private key not correct."})
		return
	}

	if !IsEthereumAddress(req.To) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. The format of receiver address is not correct."})
		return
	}

	bf := new(big.Float)
	bf.SetPrec(512)
	_, success := bf.SetString(req.Amount)
	if !success {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Format not correct."})
		return
	}
	if bf.Signbit() {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Should not be negative."})
		return
	}
	if bf.Cmp(big.NewFloat(0)) == 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Should not be zero."})
		return
	}
	if bf.Cmp(big.NewFloat(10000000)) == 1 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Too large."})
		return
	}

	Unit := new(big.Float)
	Unit.SetString(global.Uint)
	bf.Mul(bf, Unit)
	newbf1 := new(big.Float)
	newbf1.SetPrec(512)
	newbf1.SetString("1")
	if bf.Cmp(newbf1) < 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid Value. Value is less than 1 wei."})
		return
	}

	valueandfee := bf
	fullStr := bf.Text('f', -1)
	if strings.Contains(fullStr, ".") {
		if dotIndex := strings.Index(fullStr, "."); dotIndex != -1 {
			fullStr = fullStr[:dotIndex]
		}
		valueandfee = new(big.Float)
		valueandfee.SetPrec(512)
		valueandfee.SetString(fullStr)
		bf = valueandfee
	}
	log.Printf("transferToNewAccount:%+v", valueandfee.Text('f', -1))

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.RLock()
	defer d.Lock.RUnlock()

	tx1 := db.DB.Begin()
	var acc1 Account
	if err := tx1.Model(acc1).Where("addr = ?", from).Find(&acc1).Error; err != nil {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From account not exist."})
		return
	}
	bf2 := new(big.Float)
	bf2.SetPrec(512)
	bf2.SetString(acc1.Value)

	// 计算 valueandfee - bf2 的结果
	result := new(big.Float).Sub(valueandfee, bf2)
	// 如果差值等于1，则将valueandfee设置为bf2的值
	if result.Cmp(big.NewFloat(1.0)) == 0 {
		log.Printf("transferToNewAccount: valueandfee equals to bf2, reqVal, rawVal, result: %v, %v, %v \n", valueandfee, bf2, result)
		valueandfee.Set(bf2)
	}

	if bf2.Cmp(valueandfee) == -1 {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From account's balance not enough."})
		return
	}

	var acc2 Account
	if err := tx1.Model(acc2).Where("addr = ?", req.To).Find(&acc2).Error; err != nil {
		acc2.Addr = req.To
		acc2.Version = 0
		acc2.Value = "0"
		if e := tx1.Model(acc2).Create(&acc2).Error; e != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": e.Error()})
			return
		}
		if e := tx1.Model(acc2).Where("addr = ?", req.To).Find(&acc2).Error; e != nil {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": e.Error()})
			return
		}
	}

	if acc1.Addr == acc2.Addr {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. From and To is required to be different."})
		tx1.Rollback()
		return
	}

	bf3 := new(big.Float)
	bf3.SetPrec(512)
	bf3.SetString(acc2.Value)

	bff1 := new(big.Float)
	bff1.SetPrec(512)
	bff2 := new(big.Float)
	bff2.SetPrec(512)
	bff1.Sub(bf2, valueandfee)

	bff2.Add(bf3, bf)
	acc1.Value = bff1.Text('f', -1)
	acc2.Value = bff2.Text('f', -1)

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
			return
		}
		if res1.RowsAffected > 0 {
			flag1 = true
			break
		}
		time.Sleep(100 * time.Millisecond)
		tx1.Model(acc1).Where("addr = ?", from).Find(&acc1)
		bf2.SetString(acc1.Value)
		if bf2.Cmp(valueandfee) == -1 {
			tx1.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. From account's balance not enough."})
			return
		}
		bff1.Sub(bf2, valueandfee)
	}
	if !flag1 {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later."})
		return
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
			return
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
		return
	}

	tt := TX{
		From:      acc1.Addr,
		To:        acc2.Addr,
		Value:     bf.Text('f', -1),
		Timestamp: time.Now(),
	}
	if e := tx1.Model(tt).Create(&tt).Error; e != nil {
		tx1.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again."})
	}

	tx1.Commit()

	var aaa big.Int
	aaa.SetString(bf.Text('f', -1), 10)
	txlist := make([]*core.Transaction, 0)
	tx := core.NewTransaction(from, req.To, &aaa, 123, time.Now())
	tx.Fee = new(big.Int)
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
	c.JSON(http.StatusOK, gin.H{"message": "The new key has been successfully updated, and the token has been transferred."})
}
