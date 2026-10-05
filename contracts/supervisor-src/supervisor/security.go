package supervisor

import (
	"blockEmulator/db"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log"
	"math/big"
	"strings"
	"unicode"

	"github.com/ethereum/go-ethereum/crypto"
)

func checkSensitive(str string) bool { return true }

func isVisible(r rune) bool {
	// 判断字符是否为字母、数字或常见标点符号
	return unicode.IsLetter(r) || unicode.IsDigit(r) || unicode.IsPunct(r) || unicode.IsSpace(r)
}

func filterVisibleChars(input string) string {
	var result []rune
	for _, r := range input {
		if isVisible(r) {
			result = append(result, r)
		}
	}
	return string(result)
}

func checkaccexist(addr string) bool {
	var p Problem
	if err := db.DB.Model(p).Where("pk = ?", addr).Find(&p).Error; err != nil {
		return false
	}
	return true
}
func checkaccexist2(addr string) bool {
	var acc Account
	if err := db.DB.Model(acc).Where("addr = ?", addr).Find(&acc).Error; err != nil {
		return false
	}
	return true
}

func checkreplay(uuid string) bool {
	sign := Sign{Sign: uuid}
	tx := db.DB.Begin()
	if err := tx.Model(&sign).Create(&sign).Error; err != nil {
		tx.Rollback()
		return false
	}
	tx.Commit()
	return true
}

func VerifySignature_old(publickey string, data string, r1 string, s1 string) bool {
	fmt.Println("VerifySignature:", publickey)
	bytes, _ := hex.DecodeString(publickey)
	X, Y := elliptic.UnmarshalCompressed(elliptic.P256(), bytes)
	publicKey := &ecdsa.PublicKey{}
	publicKey.Curve = elliptic.P256()
	publicKey.X, publicKey.Y = X, Y
	hash := sha256.Sum256([]byte(data))
	r2, _ := hex.DecodeString(r1)
	s2, _ := hex.DecodeString(s1)
	r := new(big.Int)
	s := new(big.Int)
	r.SetBytes(r2)
	s.SetBytes(s2)
	return ecdsa.Verify(publicKey, hash[:], r, s)
}

func VerifySignature(publickey string, data string, r1 string, s1 string) bool {
	bytes, err := hex.DecodeString(publickey)
	if err != nil {
		return false
	}
	publicKey, err := crypto.UnmarshalPubkey(bytes)
	if err != nil {
		return false
	}
	hash := sha256.Sum256([]byte(data))
	r2, _ := hex.DecodeString(r1)
	s2, _ := hex.DecodeString(s1)
	r := new(big.Int)
	s := new(big.Int)
	r.SetBytes(r2)
	s.SetBytes(s2)
	return ecdsa.Verify(publicKey, hash[:], r, s)
}

func GetAddress(publickey string) string {
	bytes, err := hex.DecodeString(publickey)
	if err != nil {
		log.Panicf("GetAddress failed:publickey:%v  err: %v", publickey, err)
		return "error"
	}
	publicKey, err := crypto.UnmarshalPubkey(bytes)
	if err != nil {
		log.Panicf("GetAddress failed:publickey:%v  err: %v", publickey, err)
		return "error"
	}
	address := crypto.PubkeyToAddress(*publicKey)
	addr := strings.ToLower(address.String())
	if len(addr) > 2 && addr[:2] == "0x" {
		addr = addr[2:]
	}
	return addr
}

func check(arr [32]byte, difficulty int) bool {
	count := 0
	for i := 0; i < 32 && count < difficulty; i++ {
		for j := 0; j < 8 && count < difficulty; j++ {
			if (arr[i] & (1 << (7 - j))) != 0 {
				return false
			} else {
				count++
			}
		}
	}
	return true
}
