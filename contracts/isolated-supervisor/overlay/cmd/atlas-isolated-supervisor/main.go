package main

import (
	"blockEmulator/core"
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/params"
	"blockEmulator/supervisor"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var addressPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

func required(name string) string {
	value := os.Getenv(name)
	if value == "" {
		log.Fatalf("%s is required", name)
	}
	return value
}

func normalizedAddress(name string) string {
	value := strings.ToLower(strings.TrimPrefix(required(name), "0x"))
	if !addressPattern.MatchString(value) {
		log.Fatalf("%s must be a 20-byte hex address", name)
	}
	return value
}

func migrate() {
	models := []interface{}{
		&supervisor.PendingNode{},
		&supervisor.PendingNode2{},
		&supervisor.Problem{},
		&supervisor.Config{},
		&supervisor.Sign{},
		&supervisor.Node{},
		&supervisor.Node2{},
		&supervisor.SuperAccount{},
		&supervisor.Account{},
		&supervisor.AccountNonce{},
		&supervisor.Block{},
		&supervisor.Block2{},
		&supervisor.TX{},
		&supervisor.TX2{},
		&supervisor.TX3{},
		&supervisor.Log{},
		&supervisor.Forward{},
		&supervisor.Broker{},
		&supervisor.Claim{},
		&supervisor.Location{},
		&supervisor.Admission{},
		&supervisor.Admission2{},
		&supervisor.Apply{},
		&supervisor.Proxy{},
		&supervisor.Beat{},
		&supervisor.ChangeRate{},
		&supervisor.Stability{},
		&supervisor.Record{},
		&supervisor.IdRecord{},
		&supervisor.IdRecord2{},
		&supervisor.Ip{},
		&db.Contract{},
		&db.ContractInvoke{},
		&db.ContractStorage{},
	}
	for _, model := range models {
		if err := db.DB.AutoMigrate(model).Error; err != nil {
			log.Fatalf("migrate %T: %v", model, err)
		}
	}
	uniqueIndexes := []struct {
		model interface{}
		name  string
		field string
	}{
		{&supervisor.Config{}, "uidx_config_name", "config"},
		{&supervisor.Account{}, "uidx_account_addr", "addr"},
		{&db.ContractInvoke{}, "uidx_contract_invoke_hash", "hash"},
	}
	for _, index := range uniqueIndexes {
		if err := db.DB.Model(index.model).AddUniqueIndex(index.name, index.field).Error; err != nil {
			log.Fatalf("create unique index %s: %v", index.name, err)
		}
	}
}

func seedConfig(name, value string) {
	row := supervisor.Config{}
	if err := db.DB.Where("config = ?", name).
		Attrs(supervisor.Config{Config: name, Value: value}).
		FirstOrCreate(&row).Error; err != nil {
		log.Fatalf("seed config %s: %v", name, err)
	}
}

func seedAccount(address, balance string) {
	row := supervisor.Account{}
	if err := db.DB.Where("addr = ?", address).
		Attrs(supervisor.Account{Addr: address, Value: balance, Version: 0}).
		FirstOrCreate(&row).Error; err != nil {
		log.Fatalf("seed account %s: %v", address, err)
	}
	nonce := supervisor.AccountNonce{}
	if err := db.DB.Where("addr = ?", address).
		Attrs(supervisor.AccountNonce{Addr: address, Nonce: 0}).
		FirstOrCreate(&nonce).Error; err != nil {
		log.Fatalf("seed account nonce %s: %v", address, err)
	}
}

func main() {
	stateRoot, err := filepath.Abs(required("ATLAS_SUPERVISOR_STATE_ROOT"))
	if err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(stateRoot, 0700); err != nil {
		log.Fatal(err)
	}

	db.GlobalConfig = &db.Config{DBConf: &db.DBConf{
		Host:     "127.0.0.1",
		Port:     required("ATLAS_SUPERVISOR_DB_PORT"),
		Database: required("ATLAS_SUPERVISOR_DB_NAME"),
		User:     required("ATLAS_SUPERVISOR_DB_USER"),
		Passwd:   required("ATLAS_SUPERVISOR_DB_PASSWORD"),
		LogMod:   1,
	}}
	db.InitDB()
	defer db.DB.Close()
	migrate()

	payer := normalizedAddress("ATLAS_SUPERVISOR_PAYER_ADDRESS")
	recipient := normalizedAddress("ATLAS_SUPERVISOR_RECIPIENT_ADDRESS")
	feeSink := normalizedAddress("ATLAS_SUPERVISOR_FEE_ADDRESS")
	seedConfig("roothash", "")
	seedConfig("gasprice", "1000000000")
	seedConfig("shardid", "0")
	seedAccount(payer, "1000000000000000000000000")
	seedAccount(recipient, "0")
	seedAccount(feeSink, "0")
	global.SuperAcc = feeSink

	params.ExpDataRootDir = stateRoot
	params.DataWrite_path = filepath.Join(stateRoot, "result") + string(os.PathSeparator)
	params.LogWrite_path = filepath.Join(stateRoot, "log")
	params.DatabaseWrite_path = filepath.Join(stateRoot, "database") + string(os.PathSeparator)
	params.SupervisorAddr = "127.0.0.1:0"
	params.IPmap_nodeTable = map[uint64]map[uint64]string{}

	chainConfig := &params.ChainConfig{
		ChainID:        1051,
		Nodes_perShard: 0,
		ShardNums:      0,
		BlockSize:      uint64(params.MaxBlockSize_global),
		BlockInterval:  uint64(params.Block_Interval),
		InjectSpeed:    uint64(params.InjectSpeed),
	}
	server := new(supervisor.Supervisor)
	server.NewSupervisor(params.SupervisorAddr, chainConfig, "Relay")
	server.BuildBlockChain()
	server.TXPool = core.NewTxPool()
	fmt.Printf("isolated supervisor ready: chain_id=1051 payer=0x%s rpc=%s\n", payer, required("ATLAS_SUPERVISOR_RPC_ADDR"))
	server.RunEthRpc()
}
