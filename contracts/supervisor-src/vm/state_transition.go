package vm

import (
	"blockEmulator/core"
	"blockEmulator/global"
	"blockEmulator/vm/params"
	"encoding/hex"
	"github.com/jinzhu/gorm"
	"time"

	"fmt"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/vm"
	"math"

	"github.com/holiman/uint256"
	"math/big"
)

func ApplyMessage(evm *EVM, msg *core.Message, gp *GasPool,UUID string,TX *gorm.DB,est bool,call bool) (*ExecutionResult, error) {
	return NewStateTransition(evm, msg, gp).TransitionDb(UUID,TX,est,call)
}

type ExecutionResult struct {
	UsedGas      uint64 // Total used gas, not including the refunded gas
	RefundedGas  uint64 // Total gas refunded after execution
	Err          error  // Any error encountered during the execution(listed in core/vm/errors.go)
	ReturnData   []byte // Returned data from evm(function result or data supplied with revert opcode)
	ContractAddr common.Address

}
type StateTransition struct {
	gp           *GasPool
	msg          *core.Message
	gasRemaining uint64
	initialGas   uint64
	state        StateDB
	evm          *EVM
}

func NewStateTransition(evm *EVM, msg *core.Message, gp *GasPool) *StateTransition {
	return &StateTransition{
		gp:    gp,
		evm:   evm,
		msg:   msg,
		state: evm.StateDB,
	}
}
func (st *StateTransition) preCheck(TX *gorm.DB) error {
	// Only check transactions that are not fake
	//msg := st.msg

	//if !msg.SkipNonceChecks {
	//	// Make sure this transaction's nonce is correct.
	//	stNonce := st.state.GetNonce(msg.From)
	//	if msgNonce := msg.Nonce; stNonce < msgNonce {
	//		return fmt.Errorf("%w: address %v, tx: %d state: %d", ErrNonceTooHigh,
	//			msg.From.Hex(), msgNonce, stNonce)
	//	} else if stNonce > msgNonce {
	//		return fmt.Errorf("%w: address %v, tx: %d state: %d", ErrNonceTooLow,
	//			msg.From.Hex(), msgNonce, stNonce)
	//	} else if stNonce+1 < stNonce {
	//		return fmt.Errorf("%w: address %v, nonce: %d", ErrNonceMax,
	//			msg.From.Hex(), stNonce)
	//	}
	//}
	//if !msg.SkipFromEOACheck {
	//	// Make sure the sender is an EOA
	//	codeHash := st.state.GetCodeHash(msg.From)
	//	if codeHash != (common.Hash{}) && codeHash != types.EmptyCodeHash {
	//		return fmt.Errorf("%w: address %v, codehash: %s", ErrSenderNoEOA,
	//			msg.From.Hex(), codeHash)
	//	}
	//}

	// Make sure that transaction gasFeeCap is greater than the baseFee (post london)
	//if st.evm.ChainConfig().IsLondon(st.evm.Context.BlockNumber) {
	//	// Skip the checks if gas fields are zero and baseFee was explicitly disabled (eth_call)
	//	skipCheck := st.evm.Config.NoBaseFee && msg.GasFeeCap.BitLen() == 0 && msg.GasTipCap.BitLen() == 0
	//	if !skipCheck {
	//		if l := msg.GasFeeCap.BitLen(); l > 256 {
	//			return fmt.Errorf("%w: address %v, maxFeePerGas bit length: %d", ErrFeeCapVeryHigh,
	//				msg.From.Hex(), l)
	//		}
	//		if l := msg.GasTipCap.BitLen(); l > 256 {
	//			return fmt.Errorf("%w: address %v, maxPriorityFeePerGas bit length: %d", ErrTipVeryHigh,
	//				msg.From.Hex(), l)
	//		}
	//		if msg.GasFeeCap.Cmp(msg.GasTipCap) < 0 {
	//			return fmt.Errorf("%w: address %v, maxPriorityFeePerGas: %s, maxFeePerGas: %s", ErrTipAboveFeeCap,
	//				msg.From.Hex(), msg.GasTipCap, msg.GasFeeCap)
	//		}
	//		// This will panic if baseFee is nil, but basefee presence is verified
	//		// as part of header validation.
	//		if msg.GasFeeCap.Cmp(st.evm.Context.BaseFee) < 0 {
	//			return fmt.Errorf("%w: address %v, maxFeePerGas: %s, baseFee: %s", ErrFeeCapTooLow,
	//				msg.From.Hex(), msg.GasFeeCap, st.evm.Context.BaseFee)
	//		}
	//	}
	//}
	// Check the blob version validity
	//if msg.BlobHashes != nil {
	//	// The to field of a blob tx type is mandatory, and a `BlobTx` transaction internally
	//	// has it as a non-nillable value, so any msg derived from blob transaction has it non-nil.
	//	// However, messages created through RPC (eth_call) don't have this restriction.
	//	if msg.To == nil {
	//		return ErrBlobTxCreate
	//	}
	//	if len(msg.BlobHashes) == 0 {
	//		return ErrMissingBlobHashes
	//	}
	//	for i, hash := range msg.BlobHashes {
	//		if !kzg4844.IsValidVersionedHash(hash[:]) {
	//			return fmt.Errorf("blob %d has invalid hash version", i)
	//		}
	//	}
	//}
	// Check that the user is paying at least the current blob fee
	//if st.evm.ChainConfig().IsCancun(st.evm.Context.BlockNumber, st.evm.Context.Time) {
	//	if st.blobGasUsed() > 0 {
	//		// Skip the checks if gas fields are zero and blobBaseFee was explicitly disabled (eth_call)
	//		skipCheck := st.evm.Config.NoBaseFee && msg.BlobGasFeeCap.BitLen() == 0
	//		if !skipCheck {
	//			// This will panic if blobBaseFee is nil, but blobBaseFee presence
	//			// is verified as part of header validation.
	//			if msg.BlobGasFeeCap.Cmp(st.evm.Context.BlobBaseFee) < 0 {
	//				return fmt.Errorf("%w: address %v blobGasFeeCap: %v, blobBaseFee: %v", ErrBlobFeeCapTooLow,
	//					msg.From.Hex(), msg.BlobGasFeeCap, st.evm.Context.BlobBaseFee)
	//			}
	//		}
	//	}
	//}

	//return nil
	return st.buyGas(TX)
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
func (st *StateTransition) buyGas(TX *gorm.DB) error {
	mgval := new(big.Int).SetUint64(st.msg.GasLimit)
	mgval.Mul(mgval, st.msg.GasPrice)
	//balanceCheck := new(big.Int).Set(mgval)
	//if st.msg.GasFeeCap != nil {
	//	balanceCheck.SetUint64(st.msg.GasLimit)
	//	balanceCheck = balanceCheck.Mul(balanceCheck, st.msg.GasFeeCap)
	//}
	//balanceCheck.Add(balanceCheck, st.msg.Value)

	//if st.evm.ChainConfig().IsCancun(st.evm.Context.BlockNumber, st.evm.Context.Time) {
	//	if blobGas := st.blobGasUsed(); blobGas > 0 {
	//		// Check that the user has enough funds to cover blobGasUsed * tx.BlobGasFeeCap
	//		blobBalanceCheck := new(big.Int).SetUint64(blobGas)
	//		blobBalanceCheck.Mul(blobBalanceCheck, st.msg.BlobGasFeeCap)
	//		balanceCheck.Add(balanceCheck, blobBalanceCheck)
	//		// Pay for blobGasUsed * actual blob fee
	//		blobFee := new(big.Int).SetUint64(blobGas)
	//		blobFee.Mul(blobFee, st.evm.Context.BlobBaseFee)
	//		mgval.Add(mgval, blobFee)
	//	}
	//}
	//balanceCheckU256, overflow := uint256.FromBig(balanceCheck)
	//if overflow {
	//	return fmt.Errorf("%w: address %v required balance exceeds 256 bits", ErrInsufficientFunds, st.msg.From.Hex())
	//}
	//want :=balanceCheckU256
	addr := hex.EncodeToString(st.msg.From[:])
	var acc Account
	if TX.Model(acc).Where("addr = ?",addr).Find(&acc).Error !=nil {
		//return fmt.Errorf("%w: address %v have 0 want %v", ErrInsufficientFunds, st.msg.From.Hex(),want)
		return fmt.Errorf("%w: address %s have 0 want %s", ErrInsufficientFunds, addr, mgval)
	}


	bigInt:=new(big.Int)
	bigInt.SetString(acc.Value,10)
	var have uint256.Int
	have.SetFromBig(bigInt)

	if bigInt.Cmp(mgval) < 0{
		return fmt.Errorf("%w: address %v have %s want %s", ErrInsufficientFunds, addr, bigInt, mgval)
	}


	//if have.Cmp(want) < 0{
	//	//return fmt.Errorf("%w: address %v have %v want %v", ErrInsufficientFunds, st.msg.From.Hex(), have, want)
	//	return fmt.Errorf("%w: address %v have %v want %v", ErrInsufficientFunds, addr, have, want)
	//}

	//if have, want := st.state.GetBalance(st.msg.From), balanceCheckU256; have.Cmp(want) < 0 {
	//	return fmt.Errorf("%w: address %v have %v want %v", ErrInsufficientFunds, st.msg.From.Hex(), have, want)
	//}
	if err := st.gp.SubGas(st.msg.GasLimit); err != nil {
		return err
	}

	//if st.evm.Config.Tracer != nil && st.evm.Config.Tracer.OnGasChange != nil {
	//	st.evm.Config.Tracer.OnGasChange(0, st.msg.GasLimit, tracing.GasChangeTxInitialBalance)
	//}
	st.gasRemaining = st.msg.GasLimit

	st.initialGas = st.msg.GasLimit
	//mgvalU256, _ := uint256.FromBig(mgval)

	u := new(big.Int)
	u.Sub(bigInt,mgval)

	acc.Value = u.String()
	TX.Model(acc).Where("addr = ?",addr).Update(&acc)

	var txx TheTX
	txx.Value = mgval.String()
	txx.From = acc.Addr
	txx.To = "Gas"
	txx.Timestamp = time.Now()
	TX.Model(txx).Create(&txx)

	//st.state.SubBalance(st.msg.From, mgvalU256, tracing.BalanceDecreaseGasBuy)
	return nil
}
func (st *StateTransition) refundGas(refundQuotient uint64) uint64 {
	// Apply refund counter, capped to a refund quotient
	//最多退回 min(已消耗的gas/refundQuotient,st.state.GetRefund())
	refund := st.gasUsed() / refundQuotient
	if refund > st.state.GetRefund() {
		refund = st.state.GetRefund()
	}

	fmt.Println("refund=", refund)

	//if st.evm.Config.Tracer != nil && st.evm.Config.Tracer.OnGasChange != nil && refund > 0 {
	//	st.evm.Config.Tracer.OnGasChange(st.gasRemaining, st.gasRemaining+refund, tracing.GasChangeTxRefunds)
	//}

	st.gasRemaining += refund

	fmt.Println("gasRemaining=", st.gasRemaining)

	// Return ETH for remaining gas, exchanged at the original rate.


	//remaining := uint256.NewInt(st.gasRemaining)
	//remaining.Mul(remaining, uint256.MustFromBig(st.msg.GasPrice))


	remaining := new(big.Int).SetUint64(st.gasRemaining)
	remaining.Mul(remaining, st.msg.GasPrice)

	fmt.Println("remaining=", remaining)

	addr := hex.EncodeToString(st.msg.From[:])
	var acc Account
	if st.evm.TX.Model(acc).Where("addr = ?",addr).Find(&acc).Error !=nil {
	}

	bigInt:=new (big.Int)
	bigInt.SetString(acc.Value,10)

	bigInt.Add(remaining, bigInt)

	acc.Value = bigInt.String()
	st.evm.TX.Model(acc).Where("addr = ?",addr).Update(&acc)


	var txx TheTX
	txx.Value = remaining.String()
	txx.From = "Gas"
	txx.To = addr
	txx.Timestamp = time.Now()
	st.evm.TX.Model(txx).Create(&txx)

	//st.state.AddBalance(st.msg.From, remaining, tracing.BalanceIncreaseGasReturn)

	//if st.evm.Config.Tracer != nil && st.evm.Config.Tracer.OnGasChange != nil && st.gasRemaining > 0 {
	//	st.evm.Config.Tracer.OnGasChange(st.gasRemaining, 0, tracing.GasChangeTxLeftOverReturned)
	//}

	// Also return remaining gas to the block gas counter so it is
	// available for the next transaction.
	st.gp.AddGas(st.gasRemaining)

	return refund
}

// gasUsed returns the amount of gas used up by the state transition.
func (st *StateTransition) gasUsed() uint64 {
	return st.initialGas - st.gasRemaining
}

// blobGasUsed returns the amount of blob gas used by the message.
func (st *StateTransition) blobGasUsed() uint64 {
	return uint64(len(st.msg.BlobHashes) * params.BlobTxBlobGasPerBlob)
}
func isZeroArray(a [20]byte) bool {
	for _, v := range a {
		if v != 0 {
			return false
		}
	}
	return true
}

func IntrinsicGas(data []byte, isContractCreation bool) (uint64, error) {
	//return 0,nil

	// Set the starting gas for the raw transaction
	var gas uint64
	if isContractCreation {
		gas = params.TxGasContractCreation //创建智能合约的gas
	} else {
		gas = params.TxGas //非创建智能合约的gas
	}
	dataLen := uint64(len(data))
	// Bump the required gas by the amount of transactional data
	if dataLen > 0 {
		// Zero and non-zero bytes are priced differently
		var nz uint64
		for _, byt := range data {
			if byt != 0 {
				nz++
			}
		}
		// Make sure we don't exceed uint64 for all data combinations
		nonZeroGas := params.TxDataNonZeroGasFrontier
		if (math.MaxUint64-gas)/nonZeroGas < nz {
			return 0, ErrGasUintOverflow
		}
		gas += nz * nonZeroGas //data中非0字节的gas

		z := dataLen - nz
		if (math.MaxUint64-gas)/params.TxDataZeroGas < z {
			return 0, ErrGasUintOverflow
		}
		gas += z * params.TxDataZeroGas //data中0字节的gas

		if isContractCreation {
			lenWords := toWordSize(dataLen)
			if (math.MaxUint64-gas)/params.InitCodeWordGas < lenWords {
				return 0, ErrGasUintOverflow
			}
			gas += lenWords * params.InitCodeWordGas //创建智能合约时每个word的gas
		}
	}
	return gas, nil
}


func (st *StateTransition) TransitionDb(UUID string,TX *gorm.DB,est bool,call bool) (*ExecutionResult, error) {
	if !st.state.Exist(st.msg.From) {
		st.state.CreateAccount(st.msg.From)
		//st.state.AddBalance(msg.From, uint256.MustFromBig(setString), tracing.BalanceInilizeByXBZ)
	}

	// First check this message satisfies all consensus rules before
	// applying the message. The rules include these clauses
	//
	// 1. the nonce of the message caller is correct
	// 2. caller has enough balance to cover transaction fee(gaslimit * gasprice)
	// 3. the amount of gas required is available in the block
	// 4. the purchased gas is enough to cover intrinsic usage
	// 5. there is no overflow when calculating intrinsic gas
	// 6. caller has enough balance to cover asset transfer for **topmost** call

	// Check clauses 1-3, buy gas if everything is correct
	//先以最大可能的手续费进行扣除
	if !est && !call{
		if err := st.preCheck(TX); err != nil {
			return nil, err
		}
	}else  {
		st.gasRemaining = st.msg.GasLimit
		st.initialGas = st.msg.GasLimit
	}


	var (
		msg    = st.msg
		sender = vm.AccountRef(msg.From)
		//rules            = st.evm.ChainConfig().Rules(st.evm.Context.BlockNumber, st.evm.Context.Random != nil, st.evm.Context.Time)
		//contractCreation = msg.To == nil
		contractCreation = isZeroArray(msg.To)
	)

	// Check clauses 4-5, subtract intrinsic gas if everything is correct
	gas, err := IntrinsicGas(msg.Data, contractCreation) //合约创建的gas和data各字节的gas
	if err != nil {
		return nil, err
	}
	if st.gasRemaining < gas {
		return nil, fmt.Errorf("%w: have %d, want %d", ErrIntrinsicGas, st.gasRemaining, gas)
	}
	//if t := st.evm.Config.Tracer; t != nil && t.OnGasChange != nil {
	//	t.OnGasChange(st.gasRemaining, st.gasRemaining-gas, tracing.GasChangeTxIntrinsicGas)
	//}
	st.gasRemaining -= gas //扣除合约创建的gas和data各字节的gas

	//if rules.IsEIP4762 {
	//	st.evm.AccessEvents.AddTxOrigin(msg.From)
	//
	//	if targetAddr := msg.To; targetAddr != nil {
	//		st.evm.AccessEvents.AddTxDestination(*targetAddr, msg.Value.Sign() != 0)
	//	}
	//}

	// Check clause 6
	value, overflow := uint256.FromBig(msg.Value)
	if overflow {
		return nil, fmt.Errorf("%w: address %v", ErrInsufficientFundsForTransferOver, msg.From.Hex())
	}

	//setString, _ := new(big.Int).SetString("10000", 10)


	var acc Account
	addr:=hex.EncodeToString(msg.From[:])
	TX.Model(acc).Where("addr = ?",addr).Find(&acc)
	if !value.IsZero(){
		bigint:=new(big.Int)
		bigint.SetString(acc.Value,10)
		bb, _ :=uint256.FromBig(bigint)
		if bb.Cmp(value) < 0{
			return nil, fmt.Errorf("%w: address: %v value: %d have: %d", ErrInsufficientFundsForTransfer, addr, value.Uint64(), bb.Uint64())
		}
	}

	//from账户余额不足value
	//if !value.IsZero() && !st.evm.Context.CanTransfer(st.state, msg.From, value) {
	//	balance := st.state.GetBalance(msg.From)
	//	return nil, fmt.Errorf("%w: address: %v value: %d have: %d", ErrInsufficientFundsForTransfer, msg.From.Hex(), value.Uint64(), balance.Uint64())
	//}
	//balance := st.state.GetBalance(msg.From)
	//fmt.Printf("address have sufficient: %v value: %d have: %d \n", msg.From.Hex(), value.Uint64(), balance.Uint64())

	// Check whether the init code size has been exceeded.
	//if rules.IsShanghai && contractCreation && len(msg.Data) > params.MaxInitCodeSize {
	//	return nil, fmt.Errorf("%w: code size %v limit %v", ErrMaxInitCodeSizeExceeded, len(msg.Data), params.MaxInitCodeSize)
	//}

	// Execute the preparatory steps for state transition which includes:
	// - prepare accessList(post-berlin)
	// - reset transient storage(eip 1153)
	//st.state.Prepare(rules, msg.From, st.evm.Context.Coinbase, msg.To, ActivePrecompiles(rules), msg.AccessList)
	st.state.Prepare(params.Rules{}, msg.From, st.evm.Context.Coinbase, &msg.To, nil, msg.AccessList)

	var (
		ret   []byte
		vmerr error // vm errors do not effect consensus and are therefore not assigned to err
	)
	var contractAddr common.Address
	if contractCreation {
		//创建新合约
		ret, contractAddr, st.gasRemaining, vmerr = st.evm.Create(sender, msg.Data, st.gasRemaining, value,UUID,TX)
	} else {
		// Increment the nonce for the next transaction
		st.state.SetNonce(msg.From, st.state.GetNonce(sender.Address())+1)
		//调用合约
		ret, st.gasRemaining, vmerr = st.evm.Call(sender, st.to(), msg.Data, st.gasRemaining, value,UUID,call)
	}

	var gasRefund uint64
	//if !rules.IsLondon {
	//	// Before EIP-3529: refunds were capped to gasUsed / 2
	//gasRefund = st.refundGas(params.RefundQuotient)
	//} else {
	//	// After EIP-3529: refunds are capped to gasUsed / 5
	if !est && !call {
		gasRefund = st.refundGas(params.RefundQuotientEIP3529)
	}

	//}

	////if rules.IsLondon {
	////	effectiveTip = cmath.BigMin(msg.GasTipCap, new(big.Int).Sub(msg.GasFeeCap, st.evm.Context.BaseFee))
	////}
	effectiveTipU256 := msg.GasPrice
	//
	//if st.evm.Config.NoBaseFee && msg.GasFeeCap.Sign() == 0 && msg.GasTipCap.Sign() == 0 {
	//	// Skip fee payment when NoBaseFee is set and the fee fields
	//	// are 0. This avoids a negative effectiveTip being applied to
	//	// the coinbase when simulating calls.
	//} else {
	fee := new(big.Int).SetUint64(st.gasUsed())
	fee.Mul(fee, effectiveTipU256)


	var superacc Account
	TX.Model(superacc).Where("addr = ?",global.SuperAcc).Find(&superacc)
	superbigInt:=new(big.Int)
	superbigInt.SetString(superacc.Value,10)

	superbigInt.Add(superbigInt,fee)
	superacc.Value = superbigInt.String()
	superacc.Version = superacc.Version + 1
	TX.Model(superacc).Where("id = ?",superacc.Id).Update(&superacc)

	var txx TheTX
	txx.Value = fee.String()
	txx.From = acc.Addr
	txx.To = global.SuperAcc
	txx.Timestamp = time.Now()
	TX.Model(txx).Create(&txx)



	//st.state.AddBalance(st.evm.Context.Coinbase, fee, tracing.BalanceIncreaseRewardTransactionFee)

	//
	//	// add the coinbase to the witness iff the fee is greater than 0
	//	if rules.IsEIP4762 && fee.Sign() != 0 {
	//		st.evm.AccessEvents.AddAccount(st.evm.Context.Coinbase, true)
	//	}
	//}

	return &ExecutionResult{
		UsedGas:      st.gasUsed(),
		RefundedGas:  gasRefund,
		Err:          vmerr,
		ReturnData:   ret,
		ContractAddr: contractAddr,
	}, nil
}

func (st *StateTransition) to() common.Address {
	//if st.msg == nil || st.msg.To == nil /* contract creation */ {
	if st.msg == nil || isZeroArray(st.msg.To) /* contract creation */ {
		return common.Address{}
	}
	return st.msg.To
}
