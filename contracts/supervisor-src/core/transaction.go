// Definition of transaction

package core

import (
	"blockEmulator/utils"
	"bytes"
	"crypto/sha256"
	"encoding/gob"
	"fmt"
	"log"
	"math/big"
	"time"
)

type Transaction struct {
	Sender    utils.Address
	Recipient utils.Address
	Nonce     uint64
	Signature []byte // not implemented now.
	Value     *big.Int
	TxHash    []byte

	Time time.Time // TimeStamp the tx proposed.

	// used in transaction relaying
	Relayed bool
	// used in broker, if the tx is not a broker1 or broker2 tx, these values should be empty.
	HasBroker      bool
	SenderIsBroker bool
	OriginalSender utils.Address
	FinalRecipient utils.Address
	RawTxHash      []byte
	Data     []byte

	//B2E
	Fee       *big.Int
	IsAllocatedSender bool
	IsAllocatedRecipent bool

	SC bool
	Flag1 bool
	Flag2 bool
}

func (tx *Transaction) DeepCopy() *Transaction {
	if tx == nil {
		return nil
	}

	// 创建新的Transaction实例
	newTx := &Transaction{
		Sender:    tx.Sender,
		Recipient: tx.Recipient,
		Nonce:     tx.Nonce,
		Signature: append([]byte(nil), tx.Signature...), // 深拷贝切片
		Value:     new(big.Int).Set(tx.Value),           // 深拷贝big.Int
		TxHash:    append([]byte(nil), tx.TxHash...),    // 深拷贝切片
		Time:      tx.Time,
		Relayed:   tx.Relayed,
		HasBroker: tx.HasBroker,
		SenderIsBroker: tx.SenderIsBroker,
		OriginalSender: tx.OriginalSender,
		FinalRecipient: tx.FinalRecipient,
		IsAllocatedSender: tx.IsAllocatedSender,
		IsAllocatedRecipent: tx.IsAllocatedRecipent,
		SC: tx.SC,
		Flag1: tx.Flag1,
		Flag2: tx.Flag2,
	}

	// 处理其他需要深拷贝的字段
	if tx.Data != nil {
		newTx.Data = append([]byte(nil), tx.Data...)
	}

	if tx.RawTxHash != nil {
		newTx.RawTxHash = append([]byte(nil), tx.RawTxHash...)
	}

	if tx.Fee != nil {
		newTx.Fee = new(big.Int).Set(tx.Fee)
	}

	// 注意：utils.Address类型如果是自定义类型，需要确认其是否可比较或需要深拷贝
	// 通常如果是基本类型或固定大小的数组，可以直接赋值

	return newTx
}

func (tx *Transaction) PrintTx() string {
	vals := []interface{}{
		tx.Sender[:],
		tx.Recipient[:],
		tx.Value,
		string(tx.TxHash[:]),
	}
	res := fmt.Sprintf("%v\n", vals)
	return res
}

// Encode transaction for storing
func (tx *Transaction) Encode() []byte {
	var buff bytes.Buffer

	enc := gob.NewEncoder(&buff)
	err := enc.Encode(tx)
	if err != nil {
		log.Panic(err)
	}

	return buff.Bytes()
}

// Decode transaction
func DecodeTx(to_decode []byte) *Transaction {
	var tx Transaction

	decoder := gob.NewDecoder(bytes.NewReader(to_decode))
	err := decoder.Decode(&tx)
	if err != nil {
		log.Panic(err)
	}

	return &tx
}

// new a transaction
func NewTransaction(sender, recipient string, value *big.Int, nonce uint64, proposeTime time.Time) *Transaction {
	tx := &Transaction{
		Sender:    sender,
		Recipient: recipient,
		Value:     value,
		Nonce:     nonce,
		Time:      proposeTime,
	}

	hash := sha256.Sum256(tx.Encode())
	tx.TxHash = hash[:]
	tx.Relayed = false
	tx.FinalRecipient = ""
	tx.OriginalSender = ""
	tx.RawTxHash = nil
	tx.HasBroker = false
	tx.SenderIsBroker = false
	return tx
}

func NewTransaction2(sender, recipient string, value *big.Int, nonce uint64, proposeTime time.Time,data []byte) *Transaction {
	tx := &Transaction{
		Sender:    sender,
		Recipient: recipient,
		Value:     value,
		Nonce:     nonce,
		Time:      proposeTime,
		Data:      data,
	}

	hash := sha256.Sum256(tx.Encode())
	tx.TxHash = hash[:]
	tx.Relayed = false
	tx.FinalRecipient = ""
	tx.OriginalSender = ""
	tx.RawTxHash = nil
	tx.HasBroker = false
	tx.SenderIsBroker = false
	return tx
}
