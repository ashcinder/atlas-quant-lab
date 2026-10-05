// 派发token

package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/global"
	crand "crypto/rand"
	"errors"
	"fmt"
	"math/big"
	"sort"
	"strings"
	"time"
)

var weiFactor = big.NewInt(1_000_000_000_000_000_000) // 1e18

// 根据最近心跳时间选择收款节点
func SelectNodes[T any](activeSince time.Time) ([]T, error) {
	var nodes []T
	err := db.DB.Where("beattime > ?", activeSince).Find(&nodes).Error
	return nodes, err
}

// 论功行赏表
type IncentiveTable struct {
	Pool        Account
	TotalAmount *big.Int            // 要分发的总量
	TotalNumber int                 // 要分发的总份数
	Mapping     map[string]*big.Int //每个地址及其要分发的份额
}

func (it *IncentiveTable) Add(addr string) {
	if it.Mapping == nil {
		it.Mapping = make(map[string]*big.Int)
	}
	it.TotalNumber++
	it.Mapping[addr] = nil // 初始化为nil还是0？
}

// 平均分配，若有余数则把余数r平均分给前r个
func (it *IncentiveTable) DistributeEvenly() error {
	n := len(it.Mapping)
	if n == 0 || it.TotalAmount == nil || it.TotalAmount.Sign() < 0 {
		return errors.New("IncentiveTable: invalid state for even distribution")
	}
	it.TotalNumber = n

	den := big.NewInt(int64(n))

	share := new(big.Int).Div(new(big.Int).Set(it.TotalAmount), den)
	rem := new(big.Int).Mod(new(big.Int).Set(it.TotalAmount), den) // 0 <= rem < n

	// 固定顺序，避免 map 遍历顺序导致“谁拿余数”不确定
	addrs := make([]string, 0, n)
	for addr := range it.Mapping {
		addrs = append(addrs, addr)
	}
	sort.Strings(addrs)

	// 余数 rem 是 < n 的，因此可以安全转int64
	r := rem.Int64()

	for i, addr := range addrs {
		val := new(big.Int).Set(share) // 每人一份独立 big.Int
		if int64(i) < r {
			val.Add(val, big.NewInt(1)) // 前 r 个多 1
		}
		it.Mapping[addr] = val
	}

	return nil
}

// 随机分配
func (it *IncentiveTable) DistributeRandomly() error {
	if it.TotalNumber == 0 || it.TotalAmount == nil || it.TotalAmount.Sign() < 0 {
		return errors.New("IncentiveTable: invalid state for random distribution")
	}
	// TotalNumber 应该和 Mapping 的人数一致；若不一致，以 Mapping 为准更安全
	n := len(it.Mapping)
	if n == 0 {
		return errors.New("IncentiveTable: invalid state for random distribution")
	}
	it.TotalNumber = n

	// total + 1 用于生成 [0, total] 的均匀随机整数
	totalPlusOne := new(big.Int).Add(it.TotalAmount, big.NewInt(1))

	// 1) 生成切点：0, rand..., total
	cuts := make([]*big.Int, n+1)
	cuts[0] = big.NewInt(0)
	cuts[n] = new(big.Int).Set(it.TotalAmount)

	for i := 1; i < n; i++ {
		r, err := crand.Int(crand.Reader, totalPlusOne) // [0, total]
		if err != nil {
			// 随机源失败：退化成平均分配或直接返回都行
			return errors.New("IncentiveTable: invalid state for random distribution")
		}
		cuts[i] = r
	}

	// 2) 排序切点
	sort.Slice(cuts, func(i, j int) bool {
		return cuts[i].Cmp(cuts[j]) < 0
	})

	// 3) 相邻差值 => n 份
	shares := make([]*big.Int, n)
	for i := 0; i < n; i++ {
		shares[i] = new(big.Int).Sub(cuts[i+1], cuts[i]) // 一定 >= 0
	}

	// 4) 把 shares 分配给地址
	i := 0
	for addr := range it.Mapping {
		it.Mapping[addr] = shares[i] // shares[i] 已是独立 big.Int
		i++
	}

	return nil
}

// 根据身价进行分配，若有余数则把余数r平均分给前r个
func (it *IncentiveTable) DistributeByStake() error {
	if it.TotalAmount == nil || it.TotalAmount.Sign() < 0 {
		return errors.New("IncentiveTable: invalid TotalAmount")
	}
	if len(it.Mapping) == 0 {
		return errors.New("IncentiveTable: empty Mapping")
	}

	// 1)计算总身价，并暂存每个对象的身价
	totalStake := new(big.Int)
	addrs := make([]string, 0, len(it.Mapping))

	for addr := range it.Mapping {
		var acc Account
		if err := db.DB.Model(&Account{}).Where("addr = ?", addr).First(&acc).Error; err != nil {
			return err
		}
		stake := ValueToWei(acc.Value)
		if stake == nil || stake.Sign() < 0 {
			return errors.New("IncentiveTable: invalid stake for " + addr)
		}
		it.Mapping[addr] = stake // 写回 map：现在 Mapping 存的是 stake
		totalStake.Add(totalStake, stake)
		addrs = append(addrs, addr)
	}

	if totalStake.Sign() == 0 {
		return errors.New("IncentiveTable: totalStake is zero")
	}

	// 固定顺序，方便余数分配
	sort.Strings(addrs)

	// 按身价比例分配：reward = TotalAmount * stake / totalStake
	distributed := new(big.Int)
	rewards := make(map[string]*big.Int, len(addrs))

	for _, addr := range addrs {
		stake := it.Mapping[addr]
		r := new(big.Int).Mul(it.TotalAmount, stake)
		r.Div(r, totalStake)
		rewards[addr] = r
		distributed.Add(distributed, r)
	}

	// 处理余数，保证总和严格等于TotalAmount
	remainder := new(big.Int).Sub(it.TotalAmount, distributed)
	one := big.NewInt(1)

	// 把 remainder 的 1 单位按顺序补给前几个地址
	for i := 0; remainder.Sign() > 0; i = (i + 1) % len(addrs) {
		rewards[addrs[i]].Add(rewards[addrs[i]], one)
		remainder.Sub(remainder, one)
	}

	// 4) 最终写回Mapping：让Mapping存reward
	for _, addr := range addrs {
		it.Mapping[addr] = rewards[addr]
	}

	return nil
}

type DistributeStrategy func(table *IncentiveTable) error

func Even(table *IncentiveTable) error {
	return table.DistributeEvenly()
}

func Random(table *IncentiveTable) error {
	return table.DistributeRandomly()
}

func Stake(table *IncentiveTable) error {
	return table.DistributeByStake()
}

// 生成完整的论功行赏表
func (it *IncentiveTable) Make(pool Account, addrs []string, totalAmount *big.Int, strategy DistributeStrategy) (*IncentiveTable, error) {
	// 填入派发者与收款者
	it.Pool = pool
	for _, a := range addrs {
		it.Add(a)
	}

	// 确定派发总额
	it.TotalAmount = totalAmount

	// 确定派发方案，即给每个账户发多少
	if err := strategy(it); err != nil {
		return nil, err
	}
	return it, nil
}

// 生成适用于数据库的转账记录
func MakeTransferRecord(from string, to string, amount string) (tx TX3) {
	tx = TX3{
		From:      from,
		To:        to,
		Value:     amount,
		Timestamp: time.Now(),
		Fee:       "0",
	}
	return tx
}

// 派发
func Distribute(incentiveTable *IncentiveTable) error {
	Lock.Lock()
	defer Lock.Unlock()

	var errs []error
	// 按照方案进行派发
	for addr, reward := range incentiveTable.Mapping {
		tx := db.DB.Begin()

		// 派发
		var receiver Account
		if err := tx.Set("gorm:query_option", "FOR UPDATE").
			Where("addr = ?", addr).
			First(&receiver).Error; err != nil {
			tx.Rollback()
			errs = append(errs, err)
			continue
		}
		receiver.Value = ValuePlusBigInt(receiver.Value, reward)
		receiver.Version++
		if err := tx.Model(&receiver).Where("addr = ?", addr).Update(&receiver).Error; err != nil {
			tx.Rollback()
			errs = append(errs, err)
			continue
		}

		// 更新托管池账户（行锁，避免并发更新导致不一致）
		var poolLocked Account
		if err := tx.Set("gorm:query_option", "FOR UPDATE").
			Where("addr = ?", incentiveTable.Pool.Addr).
			First(&poolLocked).Error; err != nil {
			tx.Rollback()
			errs = append(errs, err)
			continue
		}
		poolLocked.Value = ValueMinusBigInt(poolLocked.Value, reward)
		poolLocked.Version++
		if err := tx.Model(&poolLocked).Where("addr = ?", poolLocked.Addr).Update(&poolLocked).Error; err != nil {
			tx.Rollback()
			errs = append(errs, err)
			continue
		}

		// 登记
		record := MakeTransferRecord(global.EscrowPool, addr, reward.String())
		if err := tx.Model(record).Create(&record).Error; err != nil {
			tx.Rollback()
			errs = append(errs, err)
			continue
		}

		if err := tx.Commit().Error; err != nil {
			errs = append(errs, err)
			continue
		}
	}

	if len(errs) > 0 {
		return fmt.Errorf("errors occurred during distribution: %v", errs)
	}
	return nil
}

// 单位转换
// 链上账户原生存储单位是Wei，但前端输入时为便捷采取BKC为单位。故需两种转换函数
func BKCStringToWei(s string) (*big.Int, error) {
	const decimals = 18
	parts := strings.Split(s, ".")
	intPart := parts[0]

	fracPart := ""
	if len(parts) == 2 {
		fracPart = parts[1]
	}

	// 小数部分长度不能超过 18
	if len(fracPart) > 18 {
		fracPart = fracPart[:18] // 截断（不是四舍五入）
	}

	// 不足 18 位补 0
	fracPart += strings.Repeat("0", 18-len(fracPart))

	full := intPart + fracPart

	n, ok := new(big.Int).SetString(full, 10)
	if !ok {
		return nil, fmt.Errorf("invalid number string: %s", s)
	}
	return n, nil
}

// WeiToBKCString 把 wei(整数) 格式化成 18 位小数的十进制字符串
func WeiToBKCString(x *big.Int) string {
	if x == nil {
		return "0"
	}

	neg := x.Sign() < 0
	abs := new(big.Int).Abs(x)

	quot, rem := new(big.Int), new(big.Int)
	quot.QuoRem(abs, weiFactor, rem) // abs = quot*weiFactor + rem

	intPart := quot.String()

	// rem 转成 18 位，左侧补 0
	frac := rem.String()
	if rem.Sign() == 0 {
		frac = "0"
	}
	if len(frac) < 18 {
		frac = strings.Repeat("0", 18-len(frac)) + frac
	}

	// 去掉末尾多余的 0（更像常见显示）
	frac = strings.TrimRight(frac, "0")
	if frac == "" {
		if neg && intPart != "0" {
			return "-" + intPart
		}
		return intPart
	}

	if neg {
		return "-" + intPart + "." + frac
	}
	return intPart + "." + frac
}

func IntegerStringToWei(s string) (*big.Int, bool) {
	n := new(big.Int)
	n, ok := n.SetString(s, 10)
	return n, ok
}

func ValueToWei(s string) *big.Int {
	num, ok := IntegerStringToWei(s)
	if !ok {
		return new(big.Int)
	}
	return num
}

func ValuePlusBigInt(s string, b *big.Int) string {
	host := ValueToWei(s)
	return host.Add(host, b).String()
}

func ValueMinusBigInt(s string, b *big.Int) string {
	host := ValueToWei(s)
	return host.Sub(host, b).String()
}

func isDigits(s string) bool {
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
