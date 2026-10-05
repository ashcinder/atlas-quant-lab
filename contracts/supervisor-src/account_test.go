package main

import (
	"crypto/ecdsa"
	"encoding/hex"
	"fmt"
	"log"
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

func TestGetAddress(t *testing.T) {
	p := "42356476694282309844031965206144640214016244826107483197306193721503322509724"
	privateKey := new(big.Int)
	privateKey.SetString(p, 10)
	toString := hex.EncodeToString(privateKey.Bytes())
	fmt.Println(toString)

	privKeyImported, err := crypto.ToECDSA(privateKey.Bytes())
	if err != nil {
		log.Fatalf("to ECDSA failed: %v", err)
	}
	fmt.Println(privKeyImported)
	// 检查导入后地址相同
	addr2 := crypto.PubkeyToAddress(privKeyImported.PublicKey)
	fmt.Println("Address from re-imported private key:", addr2.Hex())
}

func TestGetAddressForHex(t *testing.T) {
	p := "5da4ea8ec240f422ccd5ec5f7b1fae591347468cba4b44ff7d9c41d6f08c919c"
	privateKey := new(big.Int)
	privateKey.SetString(p, 16)
	toString := hex.EncodeToString(privateKey.Bytes())
	fmt.Println(toString)

	privKeyImported, err := crypto.ToECDSA(privateKey.Bytes())
	if err != nil {
		log.Fatalf("to ECDSA failed: %v", err)
	}
	fmt.Println(privKeyImported)
	// 检查导入后地址相同
	addr2 := crypto.PubkeyToAddress(privKeyImported.PublicKey)
	fmt.Println("Address from re-imported private key:", addr2.Hex())
}

func TestRawTx(t *testing.T) {

	rawHex := "0xf902910c843b9aca00830816508080b9023d6080604052348015600e575f5ffd5b5060405161021d38038061021d8339818101604052810190602e9190606b565b805f81905550506091565b5f5ffd5b5f819050919050565b604d81603d565b81146056575f5ffd5b50565b5f815190506065816046565b92915050565b5f60208284031215607d57607c6039565b5b5f6088848285016059565b91505092915050565b61017f8061009e5f395ff3fe608060405260043610610033575f3560e01c8063159fbdb2146100375780636d4ce63c1461005f578063c95473db14610089575b5f5ffd5b348015610042575f5ffd5b5061005d600480360381019061005891906100f6565b6100a5565b005b34801561006a575f5ffd5b506100736100ae565b6040516100809190610130565b60405180910390f35b6100a3600480360381019061009e91906100f6565b6100b6565b005b805f8190555050565b5f5f54905090565b805f8190555050565b5f5ffd5b5f819050919050565b6100d5816100c3565b81146100df575f5ffd5b50565b5f813590506100f0816100cc565b92915050565b5f6020828403121561010b5761010a6100bf565b5b5f610118848285016100e2565b91505092915050565b61012a816100c3565b82525050565b5f6020820190506101435f830184610121565b9291505056fea264697066735822122085d7cd13a5d89daf0f7b562429cdf0089ea586c52df95c089072763a949a4e7364736f6c634300081f0033000000000000000000000000000000000000000000000000000000000000045782085aa01e47770210d0697c7f3d817e4c947e4b4856b8b1c6b0e902bc27b18340fdc2e1a07d1812dbd2e9957600cc3211197d3566e905c63baa966d7acce9620d4779dd2b" // 替换成实际 raw tx

	var tx types.Transaction
	err := tx.UnmarshalBinary(common.FromHex(rawHex))
	if err != nil {
		log.Fatal("RLP decode failed:", err)
	}
	// 输出解析内容
	fmt.Println("Tx Hash:", tx.Hash().Hex())
	fmt.Println("Nonce:", tx.Nonce())
	fmt.Println("To:", tx.To())
	fmt.Println("Value:", tx.Value())
	fmt.Println("Gas Limit:", tx.Gas())
	fmt.Println("Data:", common.Bytes2Hex(tx.Data()))
	fmt.Println("ChainID:", tx.ChainId())
	fmt.Println("Type:", tx.Type()) // 0 = Legacy, 1 = AccessList, 2 = EIP-1559

	signer := types.NewLondonSigner(tx.ChainId()) // EIP-1559
	// 旧交易用 types.NewEIP155Signer(chainID)

	from, err := types.Sender(signer, &tx)
	if err != nil {
		log.Fatal("Failed to recover sender:", err)
	}

	fmt.Println("签名者地址：", from.Hex())

	// 1. 生成私钥
	privateKey, err := crypto.GenerateKey()
	if err != nil {
		log.Fatal(err)
	}

	// 私钥 Hex 格式
	privateKeyBytes := crypto.FromECDSA(privateKey)
	fmt.Printf("Private Key: %x\n", privateKeyBytes)

	// 2. 生成公钥
	publicKey := privateKey.Public()
	publicKeyECDSA, ok := publicKey.(*ecdsa.PublicKey)
	if !ok {
		log.Fatal("cannot assert type: publicKey is not of type *ecdsa.PublicKey")
	}

	publicKeyBytes := crypto.FromECDSAPub(publicKeyECDSA)
	fmt.Printf("Public Key: %x\n", publicKeyBytes)

	// 3. 生成地址
	address := crypto.PubkeyToAddress(*publicKeyECDSA)
	fmt.Printf("Address: %s\n", address.Hex())

	// (可选) 地址的字节形式
	fmt.Printf("Address Bytes: %x\n", address.Bytes())

	// (可选) EIP-55 校验和格式（默认）
	fmt.Printf("Checksummed Address: %s\n", common.HexToAddress(address.Hex()).Hex())

}
