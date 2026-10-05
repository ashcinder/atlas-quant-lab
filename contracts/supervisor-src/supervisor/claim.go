package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/global"
	"fmt"
	"math/big"
	"math/rand"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

type VerificationCode struct {
	Code      string
	ExpiresAt time.Time
}

func verifyCode(key, userInput string) bool {
	if value, ok := codeMap.Load(key); ok {
		vc := value.(VerificationCode)
		if time.Now().After(vc.ExpiresAt) {
			codeMap.Delete(key)
			return false
		}
		if vc.Code == userInput {
			codeMap.Delete(key)
			return true
		} else {
			return false
		}
	}
	return false
}
func generateRandomCode() string {
	rand.Seed(time.Now().UnixNano())   // 初始化随机种子
	code := rand.Intn(900000) + 100000 // 生成 100000~999999 的随机数
	return strconv.Itoa(code)
}
func init() {
	// 启动定时清理任务
	go cleanExpiredCodes()
}

func cleanExpiredCodes() {
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()
	time.Sleep(10 * time.Second)
	for range ticker.C {
		now := time.Now()
		var keysToDelete []interface{} // 收集需要删除的键
		codeMap.Range(func(key, value interface{}) bool {
			e := value.(VerificationCode)
			if now.After(e.ExpiresAt) {
				keysToDelete = append(keysToDelete, key)
			}
			return true
		})
		for _, key := range keysToDelete {
			codeMap.Delete(key)
		}
	}
}

var codeMap sync.Map

type rateLimiter3 struct {
	key      string
	limiters *rate.Limiter
}
type rateLimiter4 struct {
	key      string
	limiters *rate.Limiter
}

var (
	ipLimiters3 = struct {
		sync.RWMutex
		m map[string]*rateLimiter3
	}{m: make(map[string]*rateLimiter3)}
	ipLimiters4 = struct {
		sync.RWMutex
		m map[string]*rateLimiter4
	}{m: make(map[string]*rateLimiter4)}
)

func getOrNewRateLimiter3(key string) *rateLimiter3 {
	ipLimiters3.RLock()
	limiter, exists := ipLimiters3.m[key]
	ipLimiters3.RUnlock()

	if !exists {
		ipLimiters3.Lock()
		defer ipLimiters3.Unlock()

		limiter = &rateLimiter3{
			key:      key,
			limiters: rate.NewLimiter(rate.Every(60*time.Second), 1),
		}
		ipLimiters3.m[key] = limiter
	}
	return limiter
}
func getOrNewRateLimiter4(key string) *rateLimiter4 {
	ipLimiters4.RLock()
	limiter, exists := ipLimiters4.m[key]
	ipLimiters4.RUnlock()

	if !exists {
		ipLimiters4.Lock()
		defer ipLimiters4.Unlock()

		limiter = &rateLimiter4{
			key:      key,
			limiters: rate.NewLimiter(rate.Every(60*time.Second), 1),
		}
		ipLimiters4.m[key] = limiter
	}
	return limiter
}

func limit(key string) bool {
	limiter := getOrNewRateLimiter3(key)
	if !limiter.limiters.Allow() {
		return true
	}
	return false
}
func limit2(key string) bool {
	limiter := getOrNewRateLimiter4(key)
	if !limiter.limiters.Allow() {
		return true
	}
	return false
}

func getcode(c *gin.Context) {
	ip := c.ClientIP()
	if limit(ip) {
		c.JSON(http.StatusOK, gin.H{"error": "Request too frequent. 请求过于频繁"})
		return
	}
	email1 := c.Query("email")
	if limit(email1) {
		c.JSON(http.StatusOK, gin.H{"error": "Request too frequent. 请求过于频繁"})
		return
	}
	if !strings.Contains(email1, "@") {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of email."})
		return
	}

	code := generateRandomCode()

	codeMap.Store(email1, VerificationCode{
		Code:      code,
		ExpiresAt: time.Now().Add(10 * time.Minute),
	})
	err := SendEmail(email1, code)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Send code failed."})
		return
	}
	c.JSON(http.StatusOK, gin.H{"msg": "Send successfully"})
	//codeMap.Store(email, code)
}

func SendEmail(receiver string, code string) error {
	return fmt.Errorf("email delivery is disabled in the isolated Supervisor source")
}

func applyclaim(c *gin.Context) {
	if limit2(c.ClientIP()) {
		c.JSON(http.StatusOK, gin.H{"error": "Request too frequent. 请求过于频繁， IP: " + c.ClientIP()})
		return
	}
	var req Apply
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.Reason == "" || strings.TrimSpace(req.Reason) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Reason can not be empty."})
		return
	}
	if req.Email == "" || strings.TrimSpace(req.Email) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Email can not be empty."})
		return
	}
	if req.Code == "" || strings.TrimSpace(req.Code) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Code can not be empty."})
		return
	}
	if req.Token == "" || strings.TrimSpace(req.Token) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Token can not be empty."})
		return
	}
	if req.Addr == "" || strings.TrimSpace(req.Addr) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Addr can not be empty."})
		return
	}
	if !strings.Contains(req.Email, "@") {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of email."})
		return
	}

	token, err := strconv.ParseInt(req.Token, 10, 64)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of token."})
		return
	}
	if token <= 0 {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid token."})
		return
	}

	if limit2(req.Email) {
		c.JSON(http.StatusOK, gin.H{"error": "Request too frequent. 请求过于频繁"})
		return
	}

	if !verifyCode(req.Email, req.Code) {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid code."})
		return
	}
	req.Status = "Under Review"
	req.Timestamp = time.Now()
	req.Ip = c.ClientIP()
	if e := db.DB.Model(req).Create(&req).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed."})
		return
	}
	c.JSON(http.StatusOK, gin.H{"msg": "Application submitted successfully"})

}

type Reject struct {
	Id      string `json:"Id" binding:"required"`
	Comment string `json:"Comment"`
}

func rejectclaim(c *gin.Context) {
	var reject Reject
	c.ShouldBindJSON(&reject)
	id, err := strconv.Atoi(reject.Id)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of id."})
		return
	}
	var apply Apply
	db.DB.Model(apply).Where("id = ?", id).Find(&apply)
	if apply.Status == "Accepted" || apply.Status == "Rejected" {
		c.JSON(http.StatusOK, gin.H{"msg": "Apply is already reviewed"})
		return
	}
	apply.Comment = reject.Comment
	apply.Status = "Rejected"
	now := time.Now()
	apply.Timestamp2 = &now
	db.DB.Model(apply).Where("id = ?", id).Update(&apply)
	c.JSON(http.StatusOK, gin.H{"msg": "success"})
}

func acceptclaim(c *gin.Context) {
	var reject Reject
	c.ShouldBindJSON(&reject)
	id, err := strconv.Atoi(reject.Id)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of id."})
		return
	}
	c.ShouldBindJSON(&reject)
	var apply Apply
	tx := db.DB.Begin()
	if err := tx.Model(apply).Where("id = ?", id).Find(&apply).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Record not found"})
		return
	}

	if apply.Status == "Accepted" || apply.Status == "Rejected" {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"msg": "Apply is already reviewed"})
		return
	}

	apply.Comment = reject.Comment
	apply.Status = "Accepted"
	now := time.Now()
	apply.Timestamp2 = &now
	if err := tx.Model(apply).Where("id = ?", id).Update(&apply).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Update record error"})
		return
	}
	addr := apply.Addr
	var acc0 Account
	if err := tx.Model(Account{}).Where("addr = ?", addr).Find(&acc0).Error; err != nil {
		var acc Account
		acc.Addr = addr
		acc.Value = "0"
		acc.Version = 0
		if e := tx.Model(acc).Create(&acc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "失败，请稍后重试"})
			return
		}
	}

	var acc Account
	if err := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "failed"})
		return
	}
	curbigint := new(big.Float)
	curbigint.SetString(acc.Value)
	unit := new(big.Float)
	unit.SetString(global.Uint)

	addbigint := new(big.Float)
	addbigint, ok := addbigint.SetString(apply.Token)
	if !ok {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "failed"})
		return
	}
	addbigint.Mul(addbigint, unit)

	curbigint.Add(addbigint, curbigint)
	acc.Value = curbigint.Text('f', -1)
	acc.Version = acc.Version + 1
	if err := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Accept failed"})
		return
	}
	var transaction TX
	transaction.From = "Faucet Developer"
	transaction.To = acc.Addr
	transaction.Value = addbigint.Text('f', -1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Accept failed 2"})
		return
	}

	var superacc Account
	if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", "9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1").Find(&superacc).Error; e != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Accept failed 3. Try again later"})
		return
	}
	superaccbalance := new(big.Float)
	_, ok1 := superaccbalance.SetString(superacc.Value)
	if ok1 {
		superaccbalance.Sub(superaccbalance, addbigint)
		superacc.Value = superaccbalance.Text('f', -1)
		superacc.Version = superacc.Version + 1
		if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Claim failed. Try again later"})
			return
		}
	}

	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"msg": "success"})
}
func managequeryclaim2(c *gin.Context) {
	var apply []Apply
	db.DB.Model(Apply{}).Where("status = ?", "Under Review").Find(&apply)
	var res []map[string]string
	for _, app := range apply {
		m := map[string]string{
			"Id":        strconv.FormatUint(app.Id, 10),
			"Addr":      app.Addr,
			"Email":     app.Email,
			"Token":     app.Token,
			"Reason":    app.Reason,
			"Timestamp": app.Timestamp.Format("2006-01-02 15:04:05"),
			"Status":    app.Status,
			"Ip":        app.Ip,
			"Comment":   app.Comment,
		}
		if app.Timestamp2 != nil {
			m["Timestamp2"] = app.Timestamp2.Format("2006-01-02 15:04:05")
		}
		res = append(res, m)
	}
	c.JSON(http.StatusOK, gin.H{"msg": res})

}
func managequeryclaim(c *gin.Context) {
	var apply []Apply
	db.DB.Model(Apply{}).Find(&apply)
	var res []map[string]string
	for _, app := range apply {
		m := map[string]string{
			"Id":        strconv.FormatUint(app.Id, 10),
			"Addr":      app.Addr,
			"Email":     app.Email,
			"Token":     app.Token,
			"Reason":    app.Reason,
			"Timestamp": app.Timestamp.Format("2006-01-02 15:04:05"),
			"Status":    app.Status,
			"Ip":        app.Ip,
			"Comment":   app.Comment,
		}
		if app.Timestamp2 != nil {
			m["Timestamp2"] = app.Timestamp2.Format("2006-01-02 15:04:05")
		}
		res = append(res, m)
	}
	c.JSON(http.StatusOK, gin.H{"msg": res})

}
func queryclaim(c *gin.Context) {
	email1 := c.Query("email")
	if email1 == "" || strings.TrimSpace(email1) == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Email can not be empty."})
		return
	}
	if !strings.Contains(email1, "@") {
		c.JSON(http.StatusOK, gin.H{"error": "Invalid format of email."})
		return
	}
	var apply []Apply
	var res []map[string]string
	if err := db.DB.Model(Apply{}).Where("email = ?", email1).Find(&apply).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"msg": res})
		return
	}
	for _, app := range apply {
		m := map[string]string{
			"Addr":      app.Addr,
			"Email":     app.Email,
			"Token":     app.Token,
			"Reason":    app.Reason,
			"Timestamp": app.Timestamp.Format("2006-01-02 15:04:05"),
			"Status":    app.Status,
			"Comment":   app.Comment,
		}
		if app.Timestamp2 != nil {
			m["Timestamp2"] = app.Timestamp2.Format("2006-01-02 15:04:05")
		}
		res = append(res, m)
	}
	c.JSON(http.StatusOK, gin.H{"msg": res})
}
func claim2(c *gin.Context) {
	addr := c.Query("addr")
	if !checkaccexist2(addr) {
		//c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		//return
		var acc Account
		acc.Addr = addr
		acc.Value = "0"
		acc.Version = 0
		if e := db.DB.Model(acc).Create(&acc).Error; e != nil {
			c.JSON(http.StatusOK, gin.H{"error": "领取失败，请稍后重试"})
			return
		}
	}

	// 获取当前时间
	now := time.Now()
	// 计算从Unix纪元开始到现在的总秒数
	unixTimestamp := now.Unix()
	// 将秒数转换为天数
	daysSinceUnixEpoch := unixTimestamp / (24 * 60 * 60)
	days := strconv.Itoa(int(daysSinceUnixEpoch))

	var claim1 Claim
	if err := db.DB.Model(claim1).Where("addr = ? and day = ?", addr, days).First(&claim1).Error; err == nil {
		c.JSON(http.StatusOK, gin.H{"error": "Your account has claimed BKC today."})
		return
	}

	var cc Config
	if e := db.DB.Model(cc).Where("config = ?", "claimperday").Find(&cc).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}

	claimperday, _ := strconv.Atoi(cc.Value)

	var count int64
	if e := db.DB.Model(Claim{}).Where("day = ?", days).Count(&count).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	if count >= int64(claimperday) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. The number of tokens claimed today has exceeded the quota."})
		return
	}

	var count2 int64
	if e := db.DB.Model(Claim{}).Where("day = ? and Ip = ?", days, c.ClientIP()).Count(&count2).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	if count2 >= int64(10) {
		c.JSON(http.StatusOK, gin.H{"error": "Sorry. The number of tokens claimed by you today has exceeded the quota."})
		return
	}

	claim1.Addr = addr
	claim1.Day = days
	claim1.Ip = c.ClientIP()
	claim1.Timestamp = time.Now()
	tx := db.DB.Begin()
	if err := tx.Model(claim1).Create(&claim1).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Your account has claimed BKC today."})
		return
	}
	var acc Account
	if err := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}
	curbigint := new(big.Float)
	curbigint.SetString(acc.Value)
	unit := new(big.Float)
	unit.SetString(global.Uint)

	var claimconfig Config
	db.DB.Where("config = ?", "claimconfig").Find(&claimconfig)

	addbigint := new(big.Float)
	addbigint.SetString(claimconfig.Value)
	addbigint.Mul(addbigint, unit)

	curbigint.Add(addbigint, curbigint)
	acc.Value = curbigint.Text('f', -1)
	acc.Version = acc.Version + 1
	if err := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}
	var transaction TX
	transaction.From = "Faucet"
	transaction.To = acc.Addr
	transaction.Value = addbigint.Text('f', -1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}

	var superacc Account
	if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", "9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1").Find(&superacc).Error; e != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed. Try again later"})
		return
	}
	superaccbalance := new(big.Float)
	_, ok := superaccbalance.SetString(superacc.Value)
	if ok {
		superaccbalance.Sub(superaccbalance, addbigint)
		superacc.Value = superaccbalance.Text('f', -1)
		superacc.Version = superacc.Version + 1
		if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Claim failed. Try again later"})
			return
		}
	}

	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"message": "Successfully claim " + claimconfig.Value + " BKC"})

}
func claim(c *gin.Context) {
	var req ClaimReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr

	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign"})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !checkaccexist2(addr) {
		//c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		//return
		var acc Account
		acc.Addr = addr
		acc.Value = "0"
		acc.Version = 0
		if e := db.DB.Model(acc).Create(&acc).Error; e != nil {
			c.JSON(http.StatusOK, gin.H{"error": "领取失败，请稍后重试"})
			return
		}
	}

	// 获取当前时间
	now := time.Now()
	// 计算从Unix纪元开始到现在的总秒数
	unixTimestamp := now.Unix()
	// 将秒数转换为天数
	daysSinceUnixEpoch := unixTimestamp / (24 * 60 * 60)
	days := strconv.Itoa(int(daysSinceUnixEpoch))

	var claim1 Claim
	if err := db.DB.Model(claim1).Where("addr = ? and day = ?", addr, days).First(&claim1).Error; err == nil {
		c.JSON(http.StatusOK, gin.H{"error": "Your account has claimed BKC today."})
		return
	}

	var cc Config
	if e := db.DB.Model(cc).Where("config = ?", "claimperday").Find(&cc).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}

	claimperday, _ := strconv.Atoi(cc.Value)

	var count int64
	if e := db.DB.Model(Claim{}).Where("day = ?", days).Count(&count).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	if count >= int64(claimperday) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. The number of tokens claimed today has exceeded the quota."})
		return
	}
	var count2 int64
	if e := db.DB.Model(Claim{}).Where("day = ? and Ip = ?", days, c.ClientIP()).Count(&count2).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}

	var configForPerIdPerDay Config
	if e := db.DB.Model(configForPerIdPerDay).Where("config = ?", "claimperipperday").Find(&configForPerIdPerDay).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}

	configForPerIdPerDayCnt, _ := strconv.Atoi(configForPerIdPerDay.Value)
	if count2 >= int64(configForPerIdPerDayCnt) {
		c.JSON(http.StatusOK, gin.H{"error": "Sorry. The number of tokens claimed by you today has exceeded the quota."})
		return
	}
	claim1.Addr = addr
	claim1.Day = days
	claim1.Ip = c.ClientIP()
	claim1.Timestamp = time.Now()

	tx := db.DB.Begin()
	if err := tx.Model(claim1).Create(&claim1).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Your account has claimed BKC today."})
		return
	}
	var acc Account
	if err := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}
	curbigint := new(big.Float)
	curbigint.SetString(acc.Value)
	unit := new(big.Float)
	unit.SetString(global.Uint)

	var claimconfig Config
	db.DB.Where("config = ?", "claimconfig").Find(&claimconfig)

	addbigint := new(big.Float)
	addbigint.SetString(claimconfig.Value)
	addbigint.Mul(addbigint, unit)

	curbigint.Add(addbigint, curbigint)
	acc.Value = curbigint.Text('f', -1)
	acc.Version = acc.Version + 1
	if err := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}
	var transaction TX
	transaction.From = "Faucet"
	transaction.To = acc.Addr
	transaction.Value = addbigint.Text('f', -1)
	transaction.Timestamp = time.Now()
	if err := tx.Model(transaction).Create(&transaction).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed"})
		return
	}

	var superacc Account
	if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", "9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1").Find(&superacc).Error; e != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Claim failed. Try again later"})
		return
	}
	superaccbalance := new(big.Float)
	_, ok := superaccbalance.SetString(superacc.Value)
	if ok {
		superaccbalance.Sub(superaccbalance, addbigint)
		superacc.Value = superaccbalance.Text('f', -1)
		superacc.Version = superacc.Version + 1
		if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Claim failed. Try again later"})
			return
		}
	}

	tx.Commit()
	c.JSON(http.StatusOK, gin.H{"message": "Successfully claim " + claimconfig.Value + " BKC"})

}
