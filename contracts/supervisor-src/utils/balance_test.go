package utils

import (
	"errors"
	"fmt"
	"math/big"
	"testing"
)

// string(wei) -> *big.Int
func WeiStrToBigInt(weiStr string) (*big.Int, error) {
	if weiStr == "" {
		return nil, errors.New("empty wei string")
	}
	v, ok := new(big.Int).SetString(weiStr, 10)
	if !ok {
		return nil, errors.New("invalid wei string")
	}
	return v, nil
}

// *big.Int -> string(wei)
func BigIntToWeiStr(v *big.Int) string {
	if v == nil {
		return "0"
	}
	return v.String()
}

func TestWei(t *testing.T) {
	weiStr := "1071959769169367922050"
	wei, err := WeiStrToBigInt(weiStr)

	if err != nil {
		t.Fatal(err)
	}
	t.Log(BigIntToWeiStr(wei))

	eth, _ := WeiToEth(weiStr, 18)
	fmt.Println(eth)

	Unit := new(big.Float)
	Unit.SetString("1000000000000000000")
	bf := new(big.Float)
	bf.SetString(weiStr)
	bf1 := new(big.Float)
	bf1.Quo(bf, Unit)
	fmt.Println(bf1.Text('f', -1))
}
