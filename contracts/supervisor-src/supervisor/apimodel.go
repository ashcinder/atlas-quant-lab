package supervisor

type GetTransactionReceiptReq struct {
	UUID      string `json:"uuid" binding:"required"`
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type GetCodeReq struct {
	UUID      string `json:"uuid" binding:"required"`
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}
type GetBlockByNumReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
	UUID      string `json:"UUID" binding:"required"`
}
type GetBlockNumReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}
type TxRec struct {
	From              string                   `json:"from"`
	BlockHash         string                   `json:"blockHash"`
	BlockNumber       string                   `json:"blockNumber"`
	TransactionHash   string                   `json:"transactionHash"`
	TransactionIndex  string                   `json:"transactionIndex"`
	ContractAddress   interface{}              `json:"contractAddress"`
	GasUsed           string                   `json:"gasUsed"`
	Status            string                   `json:"status"`
	Logs              []map[string]interface{} `json:"logs"`
	LogsBloom         string                   `json:"logsBloom"`
	To                interface{}              `json:"to"`
	Type              string                   `json:"type"`
	CumulativeGasUsed string                   `json:"cumulativeGasUsed"`
	EffectiveGasPrice string                   `json:"effectiveGasPrice"`
	//Logs []LogItem `json:"logs"`
}
type BlockInfo struct {
	Number           string        `json:"number"`
	Hash             string        `json:"hash"`
	ParentHash       string        `json:"parentHash"`
	Nonce            string        `json:"nonce,omitempty"`
	Sha3Uncles       string        `json:"sha3Uncles"`
	LogsBloom        string        `json:"logsBloom,omitempty"`
	TransactionsRoot string        `json:"transactionsRoot"`
	StateRoot        string        `json:"stateRoot"`
	ReceiptsRoot     string        `json:"receiptsRoot"`
	Miner            string        `json:"miner"`
	Difficulty       string        `json:"difficulty"`
	TotalDifficulty  string        `json:"totalDifficulty"`
	ExtraData        string        `json:"extraData"`
	Size             string        `json:"size"`
	GasLimit         string        `json:"gasLimit"`
	GasUsed          string        `json:"gasUsed"`
	Timestamp        string        `json:"timestamp"`
	Transactions     []interface{} `json:"transactions"`
	Uncles           []string      `json:"uncles"`
}
type RpcResponse struct {
	Jsonrpc string      `json:"jsonrpc"`
	Id      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   interface{} `json:"error,omitempty"`
}
type TransactionResult struct {
	BlockHash        string `json:"blockHash"`
	BlockNumber      string `json:"blockNumber"`
	From             string `json:"from"`
	Gas              string `json:"gas"`
	GasPrice         string `json:"gasPrice"`
	Hash             string `json:"hash"`
	Input            string `json:"input"`
	Nonce            string `json:"nonce"`
	To               string `json:"to"`
	TransactionIndex string `json:"transactionIndex"`
	Value            string `json:"value"`
	V                string `json:"v"` // ECDSA签名的组成部分
	R                string `json:"r"`
	S                string `json:"s"`
}

type ConReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type SendContractReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	To        string `json:"To" `
	Data      string `json:"data" binding:"required"`
	Value     string `json:"value" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Gas       string `json:"Gas" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}
type EstContractReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	To        string `json:"To" `
	Data      string `json:"data" binding:"required"`
	Value     string `json:"value" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Gas       string `json:"Gas" `
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}
type CallContractReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	To        string `json:"To" `
	Data      string `json:"data" binding:"required"`
	Value     string `json:"value" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type GetTXByHashReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
	UUID      string `json:"UUID" binding:"required"`
}
type ReturnAccountState struct {
	AccountAddr string `json:"account"`
	Balance     string `json:"balance"`
}

type QueryisbrokerReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}
type QueryAccReq struct {
	Accounts []string `json:"accounts"`
}

type ApplybrokerReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type StakeReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
	Value     string `json:"Value" binding:"required"`
}

type QueryProfitReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type WithdrawReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type ClaimReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1     string `json:"Sign1" binding:"required"`
	Sign2     string `json:"Sign2" binding:"required"`
}

type TransactionCountReq struct {
	From        string `json:"From" binding:"required"`
	BlockHeight string `json:"BlockHeight" binding:"required"`
}
