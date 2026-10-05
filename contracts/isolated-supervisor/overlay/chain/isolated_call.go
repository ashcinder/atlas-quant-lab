package chain

import (
 "blockEmulator/core"
 "blockEmulator/db"
 "blockEmulator/vm"
 "blockEmulator/vm/state"
 "errors"
 "math/big"
 "github.com/ethereum/go-ethereum/common"
)

// IsolatedReadOnlyCall executes on a throwaway state object and rolls back SQL.
// It deliberately bypasses ExeTx's commit, receipt and block creation paths.
func IsolatedReadOnlyCall(tx *core.Transaction, statedb *state.StateDB, header *core.BlockHeader, bc *BlockChain) ([]byte,error) {
 sql := db.DB.Begin()
 if sql.Error != nil { return nil,sql.Error }
 defer sql.Rollback()
 snapshot := statedb.Snapshot()
 defer statedb.RevertToSnapshot(snapshot)
 gp := new(vm.GasPool).AddGas(2000000)
 msg := &core.Message{Nonce:0,GasLimit:gp.Gas(),GasPrice:big.NewInt(1000000000),GasFeeCap:big.NewInt(1),GasTipCap:big.NewInt(1),To:common.HexToAddress(tx.Recipient),Value:new(big.Int).Set(tx.Value),Data:tx.Data,From:common.HexToAddress(tx.Sender),SkipNonceChecks:true}
 ctx := NewEVMBlockContext(header,bc,msg.GasLimit)
 ctx.Coinbase=common.Address{}
 evm := vm.NewEVM(ctx,vm.TxContext{},statedb,nil,vm.Config{})
 evm.TX=sql
 result,err := ApplyTransactionWithEVM(msg,gp,statedb,evm,"isolated-read-only",sql,false,true)
 if err != nil { return nil,err }
 if result == nil { return nil,errors.New("missing call result") }
 if result.Err != nil { return nil,result.Err }
 return append([]byte(nil),result.ReturnData...),nil
}
