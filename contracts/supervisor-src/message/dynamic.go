package message

import "blockEmulator/core"

type GetProblemReq struct {
	PublicKey string   `json:"PublicKey" binding:"required"`
	RandomStr string   `json:"RandomStr" binding:"required"`
	Sign1      string `json:"Sign1" binding:"required"`
	Sign2      string `json:"Sign2" binding:"required"`
}

type GetProblemRes struct {
	UUID string `json:"UUID" binding:"required"`
	Difficulty string `json:"Difficulty" binding:"required"`
}

type JoinReq struct {
	PublicKey string   `json:"PublicKey" binding:"required"`
	RandomStr string   `json:"RandomStr" binding:"required"`
	Sign1      string `json:"Sign1" binding:"required"`
	Sign2      string `json:"Sign2" binding:"required"`
	Answer    string   `json:"Answer" binding:"required"`
	Ip        string   `json:"Ip" binding:"required"`
	Port      string   `json:"Port" binding:"required"`
}
type JoinReq2 struct {
	PublicKey string   `json:"PublicKey" binding:"required"`
	RandomStr string   `json:"RandomStr" binding:"required"`
	Sign1      string `json:"Sign1" binding:"required"`
	Sign2      string `json:"Sign2" binding:"required"`
	R string `json:"R" `
}

type JoinRes struct {

}

type TxReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	To string `json:"To" binding:"required"`
	Value string `json:"Value" binding:"required"`
	Sign1 string `json:"Sign1" binding:"required"`
	Sign2 string `json:"Sign2" binding:"required"`
	Fee string `json:"Fee"`
}
type QueryReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1 string `json:"Sign1" binding:"required"`
	Sign2 string `json:"Sign2" binding:"required"`
	UUID string `json:"UUID" binding:"required"`
}
type RewardReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1 string `json:"Sign1" binding:"required"`
	Sign2 string `json:"Sign2" binding:"required"`
}
type QueryReq2 struct {
	UUID string `json:"UUID" binding:"required"`
}
type ReportBlockReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
	Sign1 string `json:"Sign1" binding:"required"`
	Sign2 string `json:"Sign2" binding:"required"`
	IsLeader string `json:"IsLeader" binding:"required"`
	Root string `json:"Root" binding:"required"`
	Signs []string `json:"Signs" binding:"required"`
	Signs2     []string            `json:"Signs2" `
	BlockHash []byte `json:"BlockHash" `
	PreBlockHash []byte              `json:"PreBlockHash" `
	Txs       []*core.Transaction `json:"Txs"`
	ShardId uint64 `json:"ShardId" binding:"required"`
}

type WsReq struct {
	PublicKey string   `json:"PublicKey" binding:"required"`
	RandomStr string   `json:"RandomStr" binding:"required"`
	Sign1      string `json:"Sign1" binding:"required"`
	Sign2      string `json:"Sign2" binding:"required"`
}
type DynamicConfig struct {
	OldNodeinfos []NodeInfo `json:"OldNodeinfos" binding:"required"`
	NewNodeinfos []NodeInfo `json:"NewNodeinfos" binding:"required"`
	ProxyIp string `json:"ProxyIp" binding:"required"`
	ProxyPort string `json:"ProxyPort" binding:"required"`
}

type NodeInfo struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	Ip string `json:"Ip" binding:"required"`
	Port string `json:"Port" binding:"required"`
	ShardID string `json:"ShardID" binding:"required"`
}

type KeyPair struct {
	PublicKey  string `json:"PublicKey"`
	PrivateKey string `json:"PrivateKey"`
}