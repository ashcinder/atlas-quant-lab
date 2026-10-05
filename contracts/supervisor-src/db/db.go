package db

import (
	"fmt"
	"github.com/jinzhu/gorm"
	"time"

	// 必须要添加，解决找不到mysql驱动问题
	_ "github.com/jinzhu/gorm/dialects/mysql"
)

var (
	DB *gorm.DB
)
type Config struct {
	DBConf  *DBConf  `mapstructure:"db"`
}
var GlobalConfig *Config
type DBConf struct {
	Host     string `mapstructure:"host"`
	Port     string `mapstructure:"port"`
	Database string `mapstructure:"database"`
	User     string `mapstructure:"user"`
	Passwd   string `mapstructure:"passwd"`
	// 0: print all log
	// 1: no print log
	// 2: print error log
	LogMod int `mapstructure:"log_mod"`
}
func (dbConfig *DBConf) ToUrl() string {
	url := fmt.Sprintf("tcp(%s:%s)/%s", dbConfig.Host, dbConfig.Port, dbConfig.Database)
	return dbConfig.User + ":" + dbConfig.Passwd + "@" + url + "?charset=utf8mb4&parseTime=True&loc=Local"
}
func InitDB(){
	var err error
	DB, err = gorm.Open("mysql", GlobalConfig.DBConf.ToUrl())
	if err != nil {
		panic(err)
	}
	DB.DB().SetMaxIdleConns(50)
	DB.DB().SetMaxOpenConns(10000)
	DB.DB().SetConnMaxLifetime(time.Minute)
	DB.Set("gorm:association_autoupdate", false).Set("gorm:association_autocreate", false)
	DB.SingularTable(true)
	if GlobalConfig.DBConf.LogMod == 0 {
		DB.LogMode(true)
	}
	if GlobalConfig.DBConf.LogMod == 1 {
		DB.LogMode(false)
	}
	//DB.AutoMigrate(new(User))

	//err = DB.AutoMigrate(new(User)).Create(&User{
	//	Crt:            "123",
	//	Key:            "456",
	//	DID:           "123456",
	//}).Error
	//
	//err = DB.AutoMigrate(new(User)).Error
	//if err != nil {
	//	panic(err)
	//}
}
type Contract struct {
	Id uint64 `gorm:"primary_key;column:id;AUTO_INCREMENT"`
	Addr string `gorm:"column:addr"`
	Code []byte `gorm:"column:code;type:blob"`
	SelfDestructed int `gorm:"column:self_destructed"`
	Balance string `gorm:"column:balance"`
	Res []byte `gorm:"column:res;type:blob"`
}
func (*Contract) TableName() string {
	return "contract"
}
type ContractInvoke struct {
 Nonce uint64 `gorm:"column:nonce;type:bigint unsigned"`
	Id              uint64    `gorm:"primary_key;column:id;AUTO_INCREMENT" json:"id,omitempty"`
	Success         int       `gorm:"column:success;type:int" json:"success,omitempty"`
	Value           string    `gorm:"column:value;type:varchar(255)" json:"value,omitempty"`
	TransactionHash string    `gorm:"column:hash;type:varchar(255)" json:"transaction_hash,omitempty"`
	ContractAddress string    `gorm:"column:contract_address;type:varchar(255)" json:"contract_address,omitempty"`
	GasUsed         string    `gorm:"column:gas_used" json:"gas_used,omitempty"`
	From            string    `gorm:"column:from" json:"from,omitempty"`
	To              string    `gorm:"column:to" json:"to,omitempty"`
	Input           string    `gorm:"column:input;type:longtext" json:"input,omitempty"`
	DecodedInput    string    `gorm:"column:decoded_input;type:longtext" json:"decoded_input,omitempty"`
	Type            string    `gorm:"column:type" json:"type,omitempty"`
	GasPrice        string    `gorm:"column:gas_price" json:"gas_price,omitempty"`
	Res             string    `gorm:"column:res;type:longtext" json:"res,omitempty"`
	Time            int       `gorm:"column:time" json:"time,omitempty"`
	BlockNumber     int       `gorm:"column:block_number" json:"block_number,omitempty"`
	Timestamp       time.Time `gorm:"column:timestamp" json:"timestamp"`
	BlockHash       string    `gorm:"column:block_hash" json:"block_hash,omitempty"`
	IP              string    `gorm:"column:ip" json:"ip,omitempty"`
}
//type ContractInvoke2 struct {
//	Id uint64 `gorm:"primary_key;column:id;AUTO_INCREMENT" `
//	Success int `gorm:"column:success;type:int"`
//	Value string `gorm:"column:value;type:string"`
//	TransactionHash string `gorm:"column:hash;type:varchar(255)"`
//	ContractAddress string `gorm:"column:contract_address;type:varchar(255)"`
//	GasUsed string `gorm:"column:gas_used"`
//	From string `gorm:"column:from"`
//	To string `gorm:"column:to"`
//	Input string `gorm:"column:input;type:longtext"`
//	DecodedInput string `gorm:"column:decoded_input;type:longtext"`
//	Type string `gorm:"column:type"`
//	GasPrice string `gorm:"column:gas_price"`
//	Res string `gorm:"column:res;type:longtext"`
//	Time int `gorm:"column:time"`
//	BlockNumber int `gorm:"column:block_number"`
//	Timestamp time.Time `gorm:"column:timestamp"`
//	BlockHash string `gorm:"column:block_hash"`
//	IP string `gorm:"column:ip"`
//}
func (*ContractInvoke) TableName() string {
	return "contract_invoke"
}

type ContractStorage struct {
	Id uint64 `gorm:"primary_key;column:id;AUTO_INCREMENT"`
	ContractId uint64 `gorm:"column:contract_id;AUTO_INCREMENT"`
	Name []byte `gorm:"column:name;type:blob"`
	Value []byte `gorm:"column:value;type:blob"`
}

func (*ContractStorage) TableName() string {
	return "contract_storage"
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
