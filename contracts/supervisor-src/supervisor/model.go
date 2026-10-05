package supervisor

import "time"

type PendingNode struct {
	Id        int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	PublicKey string    `gorm:"column:publickey" json:"publickey"`
	Ip string `gorm:"column:ip" json:"ip"`
	Port string `gorm:"column:port" json:"port"`
	Beattime time.Time `gorm:"column:beattime" json:"beattime"`
}
func (*PendingNode) TableName() string {
	return "pendingnodes"
}
type PendingNode2 struct {
	Id        int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	PublicKey string    `gorm:"column:publickey" json:"publickey"`
	Ip string `gorm:"column:ip" json:"ip"`
	Port string `gorm:"column:port" json:"port"`
	Beattime time.Time `gorm:"column:beattime" json:"beattime"`
}
func (*PendingNode2) TableName() string {
	return "pendingnodes2"
}
type Problem struct {
	Id        int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	PublicKey string    `gorm:"column:pk" json:"publickey"`
	PrivateKey string    `gorm:"column:privatekey" json:"privatekey"`
	Problem   string    `gorm:"column:problem" json:"problem"`
	Difficulity int    `gorm:"column:difficulity" json:"difficulity"`
	Answer string `gorm:"column:answer" json:"answer"`
}
func (*Problem) TableName() string {
	return "problem"
}

type Config struct {
	Id int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	Config  string    `gorm:"column:config" json:"config"`
	Value   string `gorm:"column:value" json:"value"`
}

func (*Config) TableName() string {
	return "config"
}

type Sign struct {
	Id int64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	Sign string `gorm:"column:sign" json:"sign"`
}
func (*Sign) TableName() string {
	return "sign"
}

type Node struct {
	Id        int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	PublicKey string    `gorm:"column:publickey" json:"publickey"`
	Ip string `gorm:"column:ip" json:"ip"`
	Port string `gorm:"column:port" json:"port"`
	ShardId string `gorm:"column:shardid" json:"shardid"`
	NodeId string `gorm:"column:nodeid" json:"nodeid"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Beattime time.Time `gorm:"column:beattime" json:"beattime"`
}

func (*Node) TableName() string {
	return "nodes"
}
type Node2 struct {
	Id        int64     `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	PublicKey string    `gorm:"column:publickey" json:"publickey"`
	Ip string `gorm:"column:ip" json:"ip"`
	Port string `gorm:"column:port" json:"port"`
	ShardId string `gorm:"column:shardid" json:"shardid"`
	NodeId string `gorm:"column:nodeid" json:"nodeid"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Beattime time.Time `gorm:"column:beattime" json:"beattime"`
}

func (*Node2) TableName() string {
	return "nodes2"
}
type SuperAccount struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	PublicKey string    `gorm:"column:public_key" json:"publickey"`
	PrivateKey string    `gorm:"column:private_key" json:"privatekey"`
	Addr string    `gorm:"column:addr" json:"addr"`
	Value string    `gorm:"column:value" json:"value"`

}

func (*SuperAccount) TableName() string {
	return "superaccount"
}

type Account struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	Addr string    `gorm:"column:addr" json:"addr"`
	Value string    `gorm:"column:balance" json:"balance"`
	Version uint64 `gorm:"column:version" json:"version"`
}
func (*Account) TableName() string {
	return "account"
}

type Block struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	ShardId uint64    `gorm:"column:shard_id" json:"ShardId"`
	PreHash string `gorm:"column:pre_block_hash" json:"PreHash"`
	Hash string `gorm:"column:block_hash" json:"Hash"`
	Addr string `gorm:"column:addr" json:"addr"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Signs1 string `gorm:"column:signs1" json:"signs1"`
	Signs2 string `gorm:"column:signs2" json:"signs2"`
}

func (*Block) TableName() string {
	return "block"
}
type Block2 struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	ShardId uint64    `gorm:"column:shard_id" json:"ShardId"`
	PreHash string `gorm:"column:pre_block_hash" json:"PreHash"`
	Hash string `gorm:"column:block_hash" json:"Hash"`
	Addr string `gorm:"column:addr" json:"addr"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Signs1 string `gorm:"column:signs1" json:"signs1"`
	Signs2 string `gorm:"column:signs2" json:"signs2"`
}

func (*Block2) TableName() string {
	return "block2"
}
type TX struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	From string `gorm:"column:from" json:"from"`
	To string `gorm:"column:to" json:"to"`
	Value string `gorm:"column:value" json:"value"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Fee string `gorm:"column:fee" json:"fee"`
}

func (*TX) TableName() string {
	return "tx"
}

type TX2 struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	From string `gorm:"column:from" json:"from"`
	To string `gorm:"column:to" json:"to"`
	Value string `gorm:"column:value" json:"value"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Type string `gorm:"column:type" json:"type"`
}

func (*TX2) TableName() string {
	return "tx2"
}
type TX3 struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	From string `gorm:"column:from" json:"from"`
	To string `gorm:"column:to" json:"to"`
	Value string `gorm:"column:value" json:"value"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Fee string `gorm:"column:fee" json:"fee"`
}

func (*TX3) TableName() string {
	return "tx3"
}
type Log struct {
	Id          uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Address     string `gorm:"column:address"`
	Topics      string `gorm:"column:topics"`
	Data        string `gorm:"column:data"`
	BlockNumber string `gorm:"column:block_number"`
	TxHash      string `gorm:"column:txhash"`
	// index of the transaction in the block
	TxIndex string `gorm:"column:txindex"`
	// hash of the block in which the transaction was included
	BlockHash string `gorm:"column:block_hash"`
	// index of the log in the block
	Index string `gorm:"column:log_index"`

	// The Removed field is true if this log was reverted due to a chain reorganisation.
	// You must pay attention to this field if you receive logs through a filter query.
	Removed int `gorm:"column:removed"`
}

func (*Log) TableName() string {
	return "log"
}
func (*Forward) TableName() string {
	return "forward"
}

type Forward struct {
	Id        uint64    `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY" json:"id"`
	FromKey   string    `gorm:"column:fromkey" json:"from_key"`
	FromAddr  string    `gorm:"column:fromaddr" json:"from_addr"`
	ToKey     string    `gorm:"column:tokey" json:"to_key"`
	ToAddr    string    `gorm:"column:toaddr" json:"to_addr"`
	Msg       string    `gorm:"column:msg" json:"msg"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Len       int       `gorm:"column:len" json:"len"`
	Ip        string    `gorm:"column:ip" json:"ip"`
}

type Broker struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr"`
	BrokerBalance string `gorm:"column:broker_balance" json:"broker_balance"`
	LockBalance string `gorm:"column:lock_balance" json:"lock_balance"`
	ProfitBalance string `gorm:"column:profit_balance" json:"profit_balance"`
	Version uint64 `gorm:"column:version" json:"version"`
}
func (*Broker) TableName() string {
	return "broker"
}

type Claim struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr"`
	Day string `gorm:"column:day" json:"day"`
	Ip string `gorm:"column:Ip" json:"ip"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
}
func (*Claim) TableName() string {
	return "claim"
}

type Location struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr"`
	Location uint64 `gorm:"column:loc" json:"loc"`
}

func (*Location) TableName() string {
	return "loc"
}

type RootHistory struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	ShardId uint64 `gorm:"column:shardid" json:"shard_id"`
	Root string `gorm:"column:root" json:"root"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
}

type Admission struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr"`
}

func (*Admission) TableName() string {
	return "admission"
}
type Admission2 struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr"`
	Value string `gorm:"column:value" json:"value"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
}

func (*Admission2) TableName() string {
	return "admission2"
}

type Apply struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" json:"addr" binding:"required"`
	Email string `gorm:"column:email" json:"email" binding:"required"`
	Token string `gorm:"column:token" json:"token" binding:"required"`
	Reason string `gorm:"column:reason" json:"reason" binding:"required"`
	Ip string `gorm:"column:ip" json:"ip"`
	Timestamp time.Time `gorm:"column:timestamp" json:"timestamp"`
	Timestamp2 *time.Time `gorm:"column:timestamp2" json:"timestamp2"`
	Status string `gorm:"column:status" json:"status"`
	Code      string    `gorm:"-" json:"code" binding:"required"`
	Comment string `gorm:"column:comment" json:"Comment"`
}

func (*Apply) TableName() string {
	return "apply"
}

type Proxy struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	IP string `gorm:"column:ip" `
	Port string `gorm:"column:port" `
}

func (*Proxy) TableName() string {
	return "proxy"
}

type Beat struct {
	Id uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Addr string `gorm:"column:addr" `
	Timestamp time.Time `gorm:"column:timestamp" `
	Randomstr string `gorm:"column:randomstr" `
}

func (*Beat) TableName() string {
	return "beat"
}// Isolated RPC nonce persisted separately from transaction ledger rows.
type AccountNonce struct {
 Addr string `gorm:"column:addr;type:varchar(40);primary_key"`
 Nonce uint64 `gorm:"column:nonce;type:bigint unsigned"`
}
func (*AccountNonce) TableName() string { return "account_nonce" }
