package supervisor

import (
	"blockEmulator/chain"
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/partition"
	"blockEmulator/supervisor/committee"
	"blockEmulator/vm"
	"blockEmulator/vm/state"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"math/rand"
	"os"
	"net/http"
 "net"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/ulule/limiter/v3"
	mgin "github.com/ulule/limiter/v3/drivers/middleware/gin"
	"github.com/ulule/limiter/v3/drivers/store/memory"
)

type RpcRequest struct {
	Method  string        `json:"method"`
	Params  []interface{} `json:"params"`
	Id      interface{}   `json:"id"`
	Jsonrpc string        `json:"jsonrpc"`
}

func (d *Supervisor) RunEthRpc() {
	gin.DisableConsoleColor()
	r := gin.Default()
	if err := r.SetTrustedProxies([]string{"127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}); err != nil {
		log.Fatal(err)
	}
	r.Use(func(c *gin.Context) {
  if c.GetHeader("Origin") != "" { c.AbortWithStatus(http.StatusForbidden); return }
  c.Next()
 })

	// 每sec 30 次请求
	rate, _ := limiter.NewRateFromFormatted("30-S")
	store := memory.NewStore()
	instance := limiter.New(store, rate)

	// Gin 中间件
	middleware := mgin.NewMiddleware(instance, mgin.WithKeyGetter(func(c *gin.Context) string {
		return c.ClientIP()
	}))

	r.Use(middleware)

	r.GET("/test", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Hello"})
	})

	r.POST("/", func(c *gin.Context) {
		bytes1, err := io.ReadAll(c.Request.Body)
		if err != nil {
			log.Printf("Failed to read request: %v", err)
			c.JSON(http.StatusBadRequest, RpcResponse{
				Jsonrpc: "2.0",
				Id:      0,
				Error:   map[string]interface{}{"code": -32700, "message": "Parse error"},
			})
			return
		}

		var request RpcRequest
		err = json.Unmarshal(bytes1, &request)
		if err != nil {
			log.Printf("Failed to parse request: %v", err)
			c.JSON(http.StatusBadRequest, RpcResponse{
				Jsonrpc: "2.0",
				Id:      0,
				Error:   map[string]interface{}{"code": -32700, "message": "Parse error"},
			})
			return
		}

		response := RpcResponse{
			Jsonrpc: "2.0",
			Id:      request.Id,
		}
		switch request.Method {
		case "eth_gasPrice":
			response.Result = d.eth_gasPrice(request)
		//case "eth_maxPriorityFeePerGas":
		//	response.Result = eth_maxPriorityFeePerGas(request)
		case "eth_chainId":
			response.Result = d.eth_chainId(request)
		case "eth_getBlockByNumber":
			response.Result = d.eth_getBlockByNumber(request)
		case "eth_getBlockByHash":
			response.Result = d.eth_getBlockByHash(request)
		case "eth_getTransactionCount":
			response.Result = d.eth_getTransactionCount(request)
		case "net_version":
			response.Result = d.net_version(request)
		case "eth_getBalance":
			response.Result = d.eth_getBalance(request)
		case "eth_estimateGas":
			response.Result = d.eth_estimateGas(request)
		case "eth_getCode":
			response.Result = d.eth_getCode(request)
		case "eth_blockNumber":
			response.Result = d.eth_blockNumber(request)
		case "eth_getTransactionReceipt":
			response.Result = d.eth_getTransactionReceipt(request)
		case "eth_getTransactionByHash":
			response.Result = d.eth_getTransactionByHash(request)
		case "eth_call":
			response.Result = d.eth_call(request)
		case "eth_sendRawTransaction":
			aaa, e3 := d.eth_sendRawTransaction(request)
			if e3 != nil {
				response.Error = map[string]interface{}{"code": -32000, "message": e3.Error()}
			} else {
				response.Result = aaa
			}
		}
		c.JSON(http.StatusOK, response)
		return
	})
	addr := os.Getenv("ATLAS_SUPERVISOR_RPC_ADDR")
	if addr == "" {
		addr = "127.0.0.1:42515"
	}
	host, _, addressError := net.SplitHostPort(addr)
 if addressError != nil || (host != "127.0.0.1" && host != "::1") {
  log.Fatal("isolated RPC requires an explicit loopback address")
 }
 err := http.ListenAndServe(addr, r)
	if err != nil {
		log.Println(err)
	}
}
func (d *Supervisor) eth_gasPrice(request RpcRequest) interface{} {
	return "0x3b9aca00"
}

func (d *Supervisor) eth_chainId(request RpcRequest) interface{} {
	return "0x" + fmt.Sprintf("%x", 1051)
}
func (d *Supervisor) eth_getBlockByNumber(request RpcRequest) interface{} {
	u, ok := request.Params[0].(string)
	if !ok {
		log.Printf("Failed to parse request: %v", u)
		return nil
	}
	log.Printf("eth_getBlockByNumber: %v", u)
	info := new(BlockInfo)
	if u == "latest" {
		currentBlock := d.CurChain.CurrentBlock
		info.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		info.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		info.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		info.Difficulty = "0x18eba2"
		info.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		info.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		info.TotalDifficulty = "0xba39edb8"
		info.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		info.GasLimit = "0x1388"
		info.GasUsed = "0x0"
		info.Transactions = make([]interface{}, 0)
		info.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		info.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		info.Uncles = []string{}
		info.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		info.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		info.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		info.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		info.Nonce = "0x18c9465ff80c4e57"
	} else {
		number, err := strconv.ParseUint(u[2:], 16, 64)
		log.Printf("eth_getBlockByNumber: %v", number)
		if err != nil {
			return nil
		}
		currentBlock := d.CurChain.CurrentBlock
		blockHash, _ := d.CurChain.Storage.GetNewestBlockHash()
		for {
			block, err := d.CurChain.Storage.GetBlock(blockHash)
			if err != nil {
				return nil
			}
			if block.Header.Number == number {
				currentBlock = block
				break
			}
			blockHash = block.Header.ParentBlockHash
		}
		info.Number = "0x" + fmt.Sprintf("%x", currentBlock.Header.Number)
		info.Hash = "0x" + hex.EncodeToString(currentBlock.Hash)
		info.Timestamp = "0x" + fmt.Sprintf("%x", currentBlock.Header.Time.Unix())
		info.Difficulty = "0x18eba2"
		info.StateRoot = "0x" + hex.EncodeToString(currentBlock.Header.StateRoot)
		info.ParentHash = "0x" + hex.EncodeToString(currentBlock.Header.ParentBlockHash)
		info.TotalDifficulty = "0xba39edb8"
		info.ExtraData = "0xda83010a1a846765746888676f312e31382e358777696e646f7773"
		info.GasLimit = "0x1388"
		info.GasUsed = "0x0"
		info.Transactions = make([]interface{}, 0)
		info.Size = "0x" + fmt.Sprintf("%x", len(currentBlock.Encode()))
		info.LogsBloom = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
		info.Uncles = []string{}
		info.Miner = "0x7a7d03be52c12693b80de119be345aab75c50042"
		info.ReceiptsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		info.TransactionsRoot = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
		info.Sha3Uncles = "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
		info.Nonce = "0x18c9465ff80c4e57"
	}
	return info
}

func (d *Supervisor) eth_getBlockByHash(request RpcRequest) interface{} {
	s := request.Params[0].(string)
	binfo := new(BlockInfo)
	if s == "latest" {
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
		if s[:2] == "0x" {
			s = s[2:]
		}
		hash, err := hex.DecodeString(s)
		if err != nil {
			return nil
		}
		currentBlock, err := d.CurChain.Storage.GetBlock(hash)
		if err != nil {
			return nil
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
	return binfo
}

func (d *Supervisor) eth_getTransactionCount(request RpcRequest) interface{} {
 if len(request.Params) < 1 { return nil }
 from, ok := request.Params[0].(string)
 if !ok || !common.IsHexAddress(from) { return nil }
 var row AccountNonce
 if db.DB.Where("addr = ?", strings.ToLower(strings.TrimPrefix(from,"0x"))).First(&row).Error != nil { return "0x0" }
 return fmt.Sprintf("0x%x", row.Nonce)
}

func (d *Supervisor) net_version(request RpcRequest) interface{} {
	return "1"
}

func (d *Supervisor) eth_getBalance(request RpcRequest) interface{} {
	UUID := request.Params[0].(string)[2:]
	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", UUID).Find(&acc1).Error; err != nil {
		return "0x0"
	}
	Unit := new(big.Float)
	Unit.SetString(global.Uint)
	bf := new(big.Float)
	bf.SetString(acc1.Value)

	intVal := new(big.Int)
	bf.Int(intVal)
	hexStr := intVal.Text(16)
	return "0x" + hexStr
}

func (d *Supervisor) eth_estimateGas(request RpcRequest) interface{} {
	obj := request.Params[0].(map[string]interface{})
	from := ""
	if obj["from"] != nil {
		from = obj["from"].(string)[2:]
	}
	to := ""
	if obj["to"] != nil {
		to = obj["to"].(string)
	}

	value := ""
	if obj["value"] != nil {
		value = obj["value"].(string)
	}
	input1 := ""
	if obj["data"] != nil {
		input1 = obj["data"].(string)
	} else if obj["input"] != nil {
		input1 = obj["input"].(string)
	}
	rr := uuid.New().String()
	req := EstContractReq{
		To:        to,
		Data:      input1,
		Value:     value,
		RandomStr: rr,
	}

	if !checkaccexist2(from) {
		return nil
	}
	IP := ""

	Lock.Lock()
	defer Lock.Unlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", from).Find(&acc1).Error; err != nil {
		return nil
	}
	if strings.HasPrefix(req.Gas, "0x") {
		req.Gas = req.Gas[2:]
	}
	if strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 16)
	if !success {
		return nil
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
		gp         = new(vm.GasPool).AddGas(uint64(gas))
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)
	tx := core.NewTransaction(from, req.To, val, 0, time.Now())
	tx.Data = inp
	randomBytes := make([]byte, 32)
	_, _ = rand.Read(randomBytes)
	hexString := hex.EncodeToString(randomBytes)

	tx1 := db.DB.Begin()

	_, gasUsed, _, _ := chain.ExeTx(tx, statedb, d.CurChain.CurrentBlock.Header, d.CurChain, 0, gp, hexString, tx1, true, false, IP)
	gasUsed *= 10

	return "0x" + fmt.Sprintf("%x", gasUsed)
}

func (d *Supervisor) eth_getCode(request RpcRequest) interface{} {
	addr := request.Params[0].(string)[2:]
	if !checkaccexist2(addr) {
		return nil
	}

	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, err := hex.DecodeString(con.Value)
	if err != nil {
		log.Printf("eth_getCode err : %v \n", err)
		return nil
	}
	statedb, err := state.New(common.Hash(root), d.Statedb)
	if err != nil {
		log.Printf("eth_getCode err : %v \n", err)
		return nil
	}
	addr2, err := hex.DecodeString(addr)
	if err != nil {
		log.Printf("eth_getCode err : %v \n", err)
		return nil
	}
	code := statedb.GetCode(common.Address(addr2))
	return "0x" + hex.EncodeToString(code)
}

func (d *Supervisor) eth_blockNumber(request RpcRequest) interface{} {
	return "0x" + fmt.Sprintf("%x", d.CurChain.CurrentBlock.Header.Number)
}

func (d *Supervisor) eth_getTransactionReceipt(request RpcRequest) interface{} {
	u := request.Params[0].(string)[2:]
	invoke := db.ContractInvoke{}
	if db.DB.Model(invoke).Where("hash = ?", u).First(&invoke).Error != nil {
		return "0x"
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
	return mm
}

func (d *Supervisor) eth_getTransactionByHash(request RpcRequest) interface{} {
	UUID := request.Params[0].(string)[2:]
	var contractInvoke db.ContractInvoke
	if db.DB.Model(&contractInvoke).Where("hash = ?", UUID).Find(&contractInvoke).Error != nil {
		return nil
	}
	if len(contractInvoke.To) < 1 {
		contractInvoke.To = "0000000000000000000000000000000000000000"
	}
	res := &TransactionResult{
		BlockHash:        "0x" + contractInvoke.BlockHash,
		BlockNumber:      "0x" + fmt.Sprintf("%x", contractInvoke.BlockNumber),
		From:             "0x" + contractInvoke.From,
		Gas:              "0x" + contractInvoke.GasUsed,
		GasPrice:         "0x" + contractInvoke.GasPrice,
		Hash:             "0x" + contractInvoke.TransactionHash,
		Input:            "0x" + contractInvoke.Input,
		Nonce:            "0x" + fmt.Sprintf("%x", contractInvoke.Nonce),
		To:               "0x" + contractInvoke.To,
		TransactionIndex: "0x0",
		Value:            "0x" + contractInvoke.Value,
		V:                "0x25",
		R:                "0x1b5e176d927f8e9ab405058b2d2457392da3e20f328b16ddabcebc33eaac5fea",
		S:                "0x4ba69724e8f69de52f0125ad8b3c5c2cef33019bac3249e2c0a2192766d1721c",
	}

	return res
}

func (d *Supervisor) eth_call(request RpcRequest) interface{} {
 if len(request.Params) < 1 { return nil }
 obj, ok := request.Params[0].(map[string]interface{}); if !ok { return nil }
 from, _ := obj["from"].(string); to, _ := obj["to"].(string)
 if !common.IsHexAddress(from) || !common.IsHexAddress(to) { return nil }
 value, _ := obj["value"].(string); if value == "" { value = "0x0" }
 val, valid := new(big.Int).SetString(strings.TrimPrefix(value,"0x"),16); if !valid { return nil }
 data, _ := obj["data"].(string); if data == "" { data, _ = obj["input"].(string) }
 input, err := hex.DecodeString(strings.TrimPrefix(data,"0x")); if err != nil { return nil }
 Lock.Lock(); defer Lock.Unlock()
 con := Config{}; if db.DB.Where("config = ?", "roothash").First(&con).Error != nil { return nil }
 root, err := hex.DecodeString(con.Value); if err != nil { return nil }
 statedb, err := state.New(common.Hash(root),d.Statedb); if err != nil { return nil }
 tx := core.NewTransaction2(strings.ToLower(strings.TrimPrefix(from,"0x")),strings.ToLower(strings.TrimPrefix(to,"0x")),val,0,time.Now(),input)
 result, err := chain.IsolatedReadOnlyCall(tx,statedb,d.CurChain.CurrentBlock.Header,d.CurChain)
 if err != nil { return nil }
 return "0x"+hex.EncodeToString(result)
}

func (d *Supervisor) eth_sendRawTransaction(request RpcRequest) (interface{}, error) {
	rawHex := request.Params[0].(string)
	var rawTx types.Transaction
	err := rawTx.UnmarshalBinary(common.FromHex(rawHex))
	if err != nil {
		log.Printf("rawTx.UnmarshalBinary(common.FromHex(rawHex)): %v", err)
		return nil, errors.New("rawTx.UnmarshalBinary(common.FromHex(rawHex))")
	}
	var to string
	if rawTx.To() == nil {
		to = ""
	} else {
		to = strings.ToLower(rawTx.To().Hex())
	}
	gas := strconv.FormatUint(rawTx.Gas(), 10)
	value := rawTx.Value().String()
	input1 := common.Bytes2Hex(rawTx.Data())
	if len(input1) == 0 {
		input1 = "0x"
	}

	signer := types.NewLondonSigner(rawTx.ChainId()) // EIP-1559
	from, err := types.Sender(signer, &rawTx)
	if err != nil {
		return nil, err
	}
	addr := strings.ToLower(from.Hex())
	if addr[:2] == "0x" {
		addr = addr[2:]
	}
	req := SendContractReq{
		To:    to,
		Data:  input1,
		Value: value,
		Gas:   gas,
	}
	log.Printf("eth_sendRawTransaction from : %+v \n", req)
	IP := ""
	if rawTx.Type() != types.LegacyTxType { return nil, errors.New("only legacy transactions supported") }
 if rawTx.ChainId().Cmp(big.NewInt(1051)) != 0 {
		return nil, errors.New("unexpected chain ID")
	}
	rawHash := strings.TrimPrefix(rawTx.Hash().Hex(), "0x")
	Lock.Lock()
	defer Lock.Unlock()
	var known db.ContractInvoke
	if db.DB.Where("hash = ?", rawHash).First(&known).Error == nil {
		return "0x" + rawHash, nil
	}
	var nonce AccountNonce
 if err := db.DB.Where("addr = ?", addr).First(&nonce).Error; err != nil { return nil, err }
 if rawTx.Nonce() != nonce.Nonce { return nil, errors.New("unexpected account nonce") }
 d.Lock.RLock()
 defer d.Lock.RUnlock()

	var acc1 Account
	if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
		return nil, err
	}

	if req.To != "" && strings.HasPrefix(req.To, "0x") {
		req.To = req.To[2:]
	}
	val := new(big.Int)
	if strings.HasPrefix(req.Value, "0x") {
		req.Value = req.Value[2:]
	}
	_, success := val.SetString(req.Value, 10)
	if !success {
		return nil, errors.New("value error")
	}
	inp := []byte{}
	if strings.HasPrefix(req.Data, "0x") {
		inp, _ = hex.DecodeString(req.Data[2:])
	} else {
		inp, _ = hex.DecodeString(req.Data)
	}

	str := string(inp)
	if len(str) > 0 {
		visibleStr := filterVisibleChars(str)
		if len(visibleStr) > 0 {
			if !checkSensitive(visibleStr) {
				return nil, errors.New("请勿输入有害、违法等不良信息")
			}
		}
	}

	conf1 := Config{}
	db.DB.Model(conf1).Where("config = ?", "gasprice").Find(&conf1)

	gasp, validGasPrice := new(big.Int).SetString(conf1.Value, 10)
 if !validGasPrice || rawTx.GasPrice().Cmp(gasp) != 0 { return nil, errors.New("unexpected gas price") }
	mgval := new(big.Int).SetUint64(rawTx.Gas())
	mgval.Mul(mgval, gasp)
	bigInt := new(big.Int)
	bigInt.SetString(acc1.Value, 10)

	if bigInt.Cmp(new(big.Int).Add(mgval,val)) < 0 {
		return nil, errors.New("not have enough token")
	}

	con := Config{}
	db.DB.Model(con).Where("config = ?", "roothash").Find(&con)
	root, _ := hex.DecodeString(con.Value)

	var (
		gp         = new(vm.GasPool).AddGas(rawTx.Gas())
		statedb, _ = state.New(common.Hash(root), d.Statedb)
	)
	tx := core.NewTransaction2(addr, req.To, val, rawTx.Nonce(), time.Now(), inp)
	tx.Data = inp
	tx.SC = true
	hexString := rawHash

	tx1 := db.DB.Begin()
	blockHeader := d.CurChain.GenerateBlockHeader()
	log.Printf("run tx : %+v \n", tx)
	hash, _, eee, clpatxs := chain.ExeTx(tx, statedb, blockHeader, d.CurChain, 0, gp, hexString, tx1, false, false, IP)
 if eee != nil { return nil, eee }
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
		log.Printf("eee: %v", eee)
		return nil, eee
	}
	return "0x" + hexString, nil
}
