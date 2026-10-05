package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/message"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"math/big"
	"math/rand"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"golang.org/x/time/rate"
)

var (
	upgrader = websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 1024,
	}
	connections            = make(map[string]*websocket.Conn) // 用于存储活跃的WebSocket连接
	connections_senior     = make(map[string]*websocket.Conn) // 用于存储活跃的WebSocket连接
	connectionsLock        sync.Mutex
	connectionsLock_senior sync.Mutex
)

func ws(c *gin.Context) {
	ws, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Println("Upgrade error:", err)
		return
	}
	dataChan := make(chan []byte)
	go func() {
		_, message11, err1 := ws.ReadMessage()
		if err1 != nil {
			log.Println("Read error:", err)
			go func() {
				ws.Close()
			}()
			return
		}
		dataChan <- message11
	}()
	message1 := []byte{}
	select {
	case message1 = <-dataChan:

	case <-time.After(800 * time.Millisecond):
		ws.Close()
		return
	}

	w := message.WsReq{}
	err = json.Unmarshal(message1, &w)
	if err != nil {
		go func() {
			ws.Close()
		}()
		return
	}
	if w.PublicKey == "" {
		//c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	var p Problem

	addr := GetAddress(w.PublicKey)
	if err = db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
		//c.JSON(http.StatusOK, gin.H{"error": "publickey not exist"})
		go func() {
			ws.Close()
		}()
		return
	}

	if w.RandomStr == "" {
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		go func() {
			ws.Close()
		}()
		return
	}

	if !VerifySignature(w.PublicKey, w.RandomStr, w.Sign1, w.Sign2) {
		go func() {
			ws.Close()
		}()
		return
	}

	sign := Sign{Sign: w.RandomStr}
	tx0 := db.DB.Begin()
	if err = tx0.Model(&sign).Create(&sign).Error; err != nil {
		tx0.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		go func() {
			ws.Close()
		}()
		return
	}
	tx0.Commit()

	pp := PendingNode{}
	if err = db.DB.Model(&pp).Where("publickey = ?", addr).Find(&pp).Error; err != nil {
		go func() {
			ws.Close()
		}()
		return
	}

	err = ws.WriteMessage(websocket.TextMessage, []byte("success"))
	if err != nil {
		go func() {
			ws.Close()
		}()
		return
	}

	connectionsLock.Lock()
	oldws, ok := connections[addr]
	if ok {
		go func() {
			oldws.Close()
		}()
		delete(connections, addr)
	}
	connections[addr] = ws
	connectionsLock.Unlock()

	go func() {
		publickey := GetAddress(w.PublicKey)
		for {
			_, message2, err := ws.ReadMessage()
			if err != nil {
				log.Println("Read error:", err)
				//connectionsLock.Lock()
				//delete(connections, publickey)
				//connectionsLock.Unlock()
				go func() {
					ws.Close()
				}()

				break
			}
			log.Printf("Received: %s", message2)
			pp1 := PendingNode{}
			if err = db.DB.Model(&pp1).Where("publickey = ?", publickey).Find(&pp1).Error; err != nil {
				go func() {
					ws.Close()
				}()
				return
			}
			pp1.Beattime = time.Now()
			tx := db.DB.Begin()
			if err = tx.Model(&pp1).Where("id = ?", pp1.Id).Update(&pp1).Error; err != nil {
				tx.Rollback()
			}
			tx.Commit()

		}
	}()
}

//43.136.118.217
//183.42.162.117
//115.212.92.216
//113.110.140.159
//202.105.96.98
//223.88.45.249

// 27.45.244.100
// 183.42.162.117
func ws2_senior(c *gin.Context) {
	ws1, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Println("Upgrade error:", err)
		return
	}
	dataChan := make(chan []byte)
	go func() {
		_, message11, err1 := ws1.ReadMessage()
		if err1 != nil {
			log.Println("Read error:", err)
			go func() {
				ws1.Close()
			}()
			return
		}
		dataChan <- message11
	}()
	message1 := []byte{}
	select {
	case message1 = <-dataChan:

	case <-time.After(800 * time.Millisecond):
		ws1.Close()
		return
	}

	w := message.WsReq{}
	err = json.Unmarshal(message1, &w)
	if err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}
	if w.PublicKey == "" {
		//c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	//var p Problem

	addr := GetAddress(w.PublicKey)
	//if err = db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
	//	//c.JSON(http.StatusOK, gin.H{"error": "publickey not exist"})
	//	go func() {
	//		ws1.Close()
	//	}()
	//	return
	//}

	if w.RandomStr == "" {
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		go func() {
			ws1.Close()
		}()
		return
	}

	if !VerifySignature(w.PublicKey, w.RandomStr, w.Sign1, w.Sign2) {
		go func() {
			ws1.Close()
		}()
		return
	}

	sign := Sign{Sign: w.RandomStr}
	tx0 := db.DB.Begin()
	if err = tx0.Model(&sign).Create(&sign).Error; err != nil {
		tx0.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		go func() {
			ws1.Close()
		}()
		return
	}
	tx0.Commit()

	pp := PendingNode2{}
	if err = db.DB.Model(&pp).Where("publickey = ?", addr).Find(&pp).Error; err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}

	err = ws1.WriteMessage(websocket.TextMessage, []byte("success"))
	if err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}

	connectionsLock_senior.Lock()
	oldws, ok := connections_senior[addr]
	if ok {
		go func() {
			oldws.Close()
		}()
		delete(connections_senior, addr)
	}
	connections_senior[addr] = ws1
	connectionsLock_senior.Unlock()

	go func() {
		publickey := GetAddress(w.PublicKey)
		for {
			_, message2, err := ws1.ReadMessage()
			if err != nil {
				log.Println("Read error:", err)
				//connectionsLock.Lock()
				//delete(connections, publickey)
				//connectionsLock.Unlock()
				go func() {
					ws1.Close()
				}()

				break
			}
			log.Printf("Received: %s", message2)
			pp1 := PendingNode2{}
			if err = db.DB.Model(&pp1).Where("publickey = ?", publickey).Find(&pp1).Error; err != nil {
				go func() {
					ws1.Close()
				}()
				return
			}
			pp1.Beattime = time.Now()
			tx := db.DB.Begin()
			if err = tx.Model(&pp1).Where("id = ?", pp1.Id).Update(&pp1).Error; err != nil {
				tx.Rollback()
			}
			tx.Commit()

		}
	}()
}
func ws2(c *gin.Context) {
	ws1, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Println("Upgrade error:", err)
		return
	}
	dataChan := make(chan []byte)
	go func() {
		_, message11, err1 := ws1.ReadMessage()
		if err1 != nil {
			log.Println("Read error:", err)
			go func() {
				ws1.Close()
			}()
			return
		}
		dataChan <- message11
	}()
	message1 := []byte{}
	select {
	case message1 = <-dataChan:

	case <-time.After(800 * time.Millisecond):
		ws1.Close()
		return
	}

	w := message.WsReq{}
	err = json.Unmarshal(message1, &w)
	if err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}
	if w.PublicKey == "" {
		//c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	//var p Problem

	addr := GetAddress(w.PublicKey)
	//if err = db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
	//	//c.JSON(http.StatusOK, gin.H{"error": "publickey not exist"})
	//	go func() {
	//		ws1.Close()
	//	}()
	//	return
	//}

	if w.RandomStr == "" {
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		go func() {
			ws1.Close()
		}()
		return
	}

	if !VerifySignature(w.PublicKey, w.RandomStr, w.Sign1, w.Sign2) {
		go func() {
			ws1.Close()
		}()
		return
	}

	sign := Sign{Sign: w.RandomStr}
	tx0 := db.DB.Begin()
	if err = tx0.Model(&sign).Create(&sign).Error; err != nil {
		tx0.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		go func() {
			ws1.Close()
		}()
		return
	}
	tx0.Commit()

	pp := PendingNode{}
	if err = db.DB.Model(&pp).Where("publickey = ?", addr).Find(&pp).Error; err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}

	err = ws1.WriteMessage(websocket.TextMessage, []byte("success"))
	if err != nil {
		go func() {
			ws1.Close()
		}()
		return
	}

	connectionsLock.Lock()
	oldws, ok := connections[addr]
	if ok {
		go func() {
			oldws.Close()
		}()
		delete(connections, addr)
	}
	connections[addr] = ws1
	connectionsLock.Unlock()

	go func() {
		publickey := GetAddress(w.PublicKey)
		for {
			_, message2, err := ws1.ReadMessage()
			if err != nil {
				log.Println("Read error:", err)
				//connectionsLock.Lock()
				//delete(connections, publickey)
				//connectionsLock.Unlock()
				go func() {
					ws1.Close()
				}()

				break
			}
			log.Printf("Received: %s", message2)
			pp1 := PendingNode{}
			if err = db.DB.Model(&pp1).Where("publickey = ?", publickey).Find(&pp1).Error; err != nil {
				go func() {
					ws1.Close()
				}()
				return
			}
			pp1.Beattime = time.Now()
			tx := db.DB.Begin()
			if err = tx.Model(&pp1).Where("id = ?", pp1.Id).Update(&pp1).Error; err != nil {
				tx.Rollback()
			}
			tx.Commit()

		}
	}()
}
func GetVersion(c *gin.Context) {
	var cc Config
	db.DB.Where("config = ?", "version").Find(&cc)
	version := cc.Value
	c.String(http.StatusOK, version)
}

func getProblem(c *gin.Context) {
	var req message.GetProblemReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body"})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	if req.RandomStr == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		return
	}
	thedata := req.RandomStr
	if !VerifySignature(req.PublicKey, thedata, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: Invalid sign"})
		return
	}

	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}

	addr := GetAddress(req.PublicKey)
	var p Problem
	if err := db.DB.Model(p).Where("pk = ?", addr).Find(&p).Error; err != nil {
		p.PublicKey = addr
		db.DB.Model(p).Create(&p)
		db.DB.Model(p).Where("pk = ?", addr).Find(&p)
	}

	randomStr := uuid.New().String()
	var diff Config
	db.DB.Where("config = ?", "difficulity").Find(&diff)
	p.Problem = randomStr
	atoi, _ := strconv.Atoi(diff.Value)
	p.Difficulity = atoi

	tx := db.DB.Begin()
	if err := tx.Model(&p).Where("id = ?", p.Id).Update(&p).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "create problem error"})
		return
	}
	if err := tx.Commit().Error; err != nil {
		fmt.Println(err)
	}
	var res message.GetProblemRes
	res.UUID = randomStr
	res.Difficulty = strconv.Itoa(p.Difficulity)
	c.JSON(http.StatusOK, gin.H{"message": "create problem success", "data": res})
}
func join(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req message.JoinReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body"})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	if req.RandomStr == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		return
	}
	if !VerifySignature(req.PublicKey, req.RandomStr, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid sign."})
		return
	}
	if !checkreplay(req.RandomStr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid sign, replay attack detected"})
		return
	}

	addr := GetAddress(req.PublicKey)
	var p Problem
	if err := db.DB.Where("pk = ?", addr).Find(&p).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}

	s2 := addr + p.Problem + req.Answer
	bytes := sha256.Sum256([]byte(s2))
	if !check(bytes, p.Difficulity) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid answer"})
		return
	}
	p.Answer = req.Answer

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.Lock()
	defer d.Lock.Unlock()

	tx := db.DB.Begin()
	if err := tx.Model(&p).Where("id = ?", p.Id).Update(&p).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "update problem error"})
		return
	}

	//a := atomic.Bool{}
	//wg := sync.WaitGroup{}
	//wg.Add(1)
	//go func() {
	//	ConnectionMapLock.RLock()
	//	defer ConnectionMapLock.RUnlock()
	//	defer wg.Done()
	//	for k, v := range CMap {
	//		if v == addr {
	//			conn,ok := ConnectionMap[k]
	//			if ok {
	//				msg := message.MergeMessage(message.CPing, []byte(""))
	//				_, err := conn.Write(msg)
	//				if err == nil {
	//					a.Store(true)
	//					return
	//				}
	//				//if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 == nil {
	//				//a.Store(true)
	//				//return
	//				//}
	//			}
	//		}
	//	}
	//}()
	//
	//wg.Wait()
	//if a.Load(){
	//	//c.JSON(http.StatusOK, gin.H{"error": "do not join system using the same private key"})
	//	//tx.Rollback()
	//	//return
	//}

	host, port, _ := net.SplitHostPort(strings.TrimSpace(c.Request.RemoteAddr))

	var checkNode PendingNode
	if tx.Model(checkNode).Where("publickey = ?", addr).Find(&checkNode).Error != nil {
		//tx.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		//return
		n := PendingNode{
			PublicKey: addr,
			Ip:        host,
			Port:      port,
			Beattime:  time.Now(),
		}
		if err := tx.Model(&n).Create(&n).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
	}

	var checkAcc Account
	if tx.Model(checkAcc).Where("addr = ?", addr).Find(&checkAcc).Error == nil {
		tx.Commit()
		c.JSON(http.StatusOK, gin.H{"message": "success"})
		return
	}

	var account Account
	account.Addr = addr
	account.Value = "0"
	account.Version = 0
	if err := tx.Model(account).Create(&account).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}

	var cc Config
	db.DB.Model(cc).Where("config = ?", "shardid").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)
	rand.Seed(time.Now().UnixNano())
	intn := rand.Intn(shardNum)
	//var loc Location
	//loc.Addr = addr
	//loc.Location = uint64(intn)
	//if err := tx.Model(loc).Create(&loc).Error; err != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
	//	return
	//}

	var loc Location
	if tx.Model(loc).Where("addr = ?", addr).Find(&loc).Error != nil {
		loc.Location = uint64(intn)
		loc.Addr = addr
		if err := tx.Model(loc).Create(&loc).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
	}
	tx.Commit()

	c.JSON(http.StatusOK, gin.H{"message": "success"})
}

type BeatReq struct {
	PublicKey string `json:"PublicKey" binding:"required"`
	RandomStr string `json:"RandomStr" binding:"required"`
}

func beat(c *gin.Context) {
	var req BeatReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body"})
		return
	}
	addr := GetAddress(req.PublicKey)
	if !IsEthereumAddress(addr) {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid address"})
		return
	}
	var b Beat
	if db.DB.Model(b).Where("addr = ?", addr).Find(&b).Error != nil {
		b.Addr = addr
		b.Timestamp = time.Now()
		b.Randomstr = req.RandomStr
		if err := db.DB.Model(b).Create(&b).Error; err != nil {
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"message": "success update for first join"})
		return
	}
	b.Timestamp = time.Now()
	if err := db.DB.Model(b).Where("id = ?", b.Id).Update(&b).Error; err != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "success"})
}

func join2_senior(c *gin.Context) {
	d := c.MustGet("supervisor").(*Supervisor)
	var req message.JoinReq2
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body"})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	if req.RandomStr == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		return
	}
	if !VerifySignature(req.PublicKey, req.RandomStr, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid sign."})
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
			c.JSON(http.StatusOK, gin.H{"error": "Join failed, try again later..."})
			return
		}
	}

	ip := c.RemoteIP()
	var nodes []Node2
	countN := 0
	db.DB.Model(Node2{}).Where("ip = ?", ip).Find(&nodes)
	if len(nodes) > 0 {
		for _, node := range nodes {
			if time.Since(node.Beattime).Seconds() < 120 {
				countN++
			}
		}
	}

	var cMaxNodePerIp Config
	if e := db.DB.Model(cMaxNodePerIp).Where("config = ?", "max_node_num_per_ip").Find(&cMaxNodePerIp).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	cMaxNodePerIpVal, _ := strconv.Atoi(cMaxNodePerIp.Value)

	if countN >= cMaxNodePerIpVal {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Can not launch too many nodes."})
		return
	}

	var pnodes []PendingNode2
	db.DB.Model(PendingNode2{}).Where("ip = ?", ip).Find(&pnodes)
	if len(pnodes) > 0 {
		for _, node := range pnodes {
			if time.Since(node.Beattime).Seconds() < 120 {
				countN++
			}
		}
	}
	if countN >= cMaxNodePerIpVal {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Can not launch too many nodes."})
		return
	}

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.Lock()
	defer d.Lock.Unlock()

	tx := db.DB.Begin()

	var admission Admission2
	if tx.Model(admission).Where("addr = ?", addr).First(&admission).Error != nil {
		unit := new(big.Int)
		unit.SetString(global.Uint, 10)
		var cc1 Config
		if e := tx.Model(cc1).Where("config = ?", "ticket_senior").Find(&cc1).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
		ticket := new(big.Int)
		ticket.SetString(cc1.Value, 10)
		ticket.Mul(ticket, unit)
		var acc Account
		if e := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later1"})
			return
		}
		balancebi := new(big.Int)
		balance := acc.Value
		if strings.Contains(acc.Value, ".") {
			balance = strings.Split(acc.Value, ".")[0]
		}
		balancebi.SetString(balance, 10)
		if balancebi.Cmp(ticket) < 0 {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join senior shard failed. Your account's balance is less than " + cc1.Value + " BKC."})
			return
		}
		balancebi.Sub(balancebi, ticket)
		acc.Value = balancebi.String()
		acc.Version = acc.Version + 1
		if e := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later2"})
			return
		}
		var TX_ TX3
		TX_.From = acc.Addr
		TX_.To = global.EscrowPool
		TX_.Value = ticket.String()
		TX_.Timestamp = time.Now()
		TX_.Fee = "0"
		if e := tx.Model(TX_).Create(&TX_).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later3"})
			return
		}
		admission.Addr = acc.Addr
		admission.Value = ticket.String()
		admission.Timestamp = time.Now()
		if e := tx.Model(admission).Create(&admission).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later4"})
			return
		}
		var superacc Account
		if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", global.EscrowPool).Find(&superacc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later5"})
			return
		}
		superaccbalance := new(big.Int)
		_, ok := superaccbalance.SetString(superacc.Value, 10)
		if ok {
			superaccbalance.Add(superaccbalance, ticket)
			superacc.Value = superaccbalance.String()
			superacc.Version = superacc.Version + 1
			if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
				tx.Rollback()
				c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later6"})
				return
			}
		}
		var b Beat
		if tx.Model(b).Where("addr = ?", addr).First(&b).Error == nil {
			b.Randomstr = req.R
			tx.Model(b).Where("id = ?", b.Id).Update(&b)
		}

	} else {
		var b Beat
		if tx.Model(b).Where("addr = ?", addr).First(&b).Error != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later7"})
			return
		} else {
			if time.Since(b.Timestamp).Seconds() <= (60 * 15) {
				if b.Randomstr != req.R {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error:": "It is prohibited to use the same account to join BrokerChain."})
					return
				}
			} else {
				unit := new(big.Int)
				unit.SetString(global.Uint, 10)
				var cc1 Config
				if e := tx.Model(cc1).Where("config = ?", "ticket_senior").Find(&cc1).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
					return
				}
				ticket := new(big.Int)
				ticket.SetString(cc1.Value, 10)
				ticket.Mul(ticket, unit)
				var acc Account
				if e := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later8"})
					return
				}
				balancebi := new(big.Int)
				balance := acc.Value
				if strings.Contains(acc.Value, ".") {
					balance = strings.Split(acc.Value, ".")[0]
				}
				balancebi.SetString(balance, 10)
				if balancebi.Cmp(ticket) < 0 {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join senior shard failed. Your account's balance is less than " + cc1.Value + " BKC."})
					return
				}
				balancebi.Sub(balancebi, ticket)
				acc.Value = balancebi.String()
				acc.Version = acc.Version + 1
				if e := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later9"})
					return
				}
				var TX_ TX3
				TX_.From = acc.Addr
				TX_.To = global.EscrowPool
				TX_.Value = ticket.String()
				TX_.Timestamp = time.Now()
				TX_.Fee = "0"
				if e := tx.Model(TX_).Create(&TX_).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later10"})
					return
				}
				var admission_ Admission2
				admission_.Addr = acc.Addr
				admission_.Value = ticket.String()
				admission_.Timestamp = time.Now()
				if e := tx.Model(admission).Create(&admission_).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later11"})
					return
				}
				var superacc Account
				if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", global.EscrowPool).Find(&superacc).Error; e != nil {
					tx.Rollback()
					c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later12"})
					return
				}
				superaccbalance := new(big.Int)
				_, ok := superaccbalance.SetString(superacc.Value, 10)
				if ok {
					superaccbalance.Add(superaccbalance, ticket)
					superacc.Value = superaccbalance.String()
					superacc.Version = superacc.Version + 1
					if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
						tx.Rollback()
						c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later13"})
						return
					}
				}
				b.Randomstr = req.R
				tx.Model(b).Where("id = ?", b.Id).Update(&b)
			}
		}
	}
	tx.Commit()

	host, port, _ := net.SplitHostPort(strings.TrimSpace(c.Request.RemoteAddr))

	tx = db.DB.Begin()
	var checkNode PendingNode2
	if tx.Model(checkNode).Where("publickey = ?", addr).Find(&checkNode).Error != nil {
		//tx.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		//return
		n := PendingNode2{
			PublicKey: addr,
			Ip:        host,
			Port:      port,
			Beattime:  time.Now(),
		}
		if err := tx.Model(&n).Create(&n).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later14"})
			return
		}
	}
	var cc Config
	db.DB.Model(cc).Where("config = ?", "shardid_senior").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)
	rand.Seed(time.Now().UnixNano())
	intn := rand.Intn(shardNum)
	//var loc Location
	//loc.Addr = addr
	//loc.Location = uint64(intn)
	//if err := tx.Model(loc).Create(&loc).Error; err != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
	//	return
	//}

	var loc Location
	if tx.Model(loc).Where("addr = ?", addr).Find(&loc).Error != nil {
		loc.Location = uint64(intn)
		loc.Addr = addr
		if err := tx.Model(loc).Create(&loc).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later15"})
			return
		}
	}

	tx.Commit()

	c.JSON(http.StatusOK, gin.H{"message": "success"})
}

// LimiterManager 管理每个 IP 的限流器
type LimiterManager struct {
	limiters sync.Map // map[string]*rate.Limiter
}

// NewLimiterManager 创建新的限流管理器
func NewLimiterManager() *LimiterManager {
	return &LimiterManager{}
}

// getLimiter 获取或创建指定 IP 的限流器
func (lm *LimiterManager) getLimiter(ip string) *rate.Limiter {
	// 先尝试读取
	if limiter, ok := lm.limiters.Load(ip); ok {
		return limiter.(*rate.Limiter)
	}

	// 不存在则创建（每秒 10 次，突发为 10）
	newLimiter := rate.NewLimiter(rate.Limit(10), 10)

	// 存入 map（可能多个 goroutine 同时创建，但最终只有一个生效，可接受）
	actual, loaded := lm.limiters.LoadOrStore(ip, newLimiter)
	if loaded {
		return actual.(*rate.Limiter)
	}
	return newLimiter
}

// Allow 检查是否允许该 IP 的请求
func (lm *LimiterManager) Allow(ip string) bool {
	return lm.getLimiter(ip).Allow()
}

var limiterManager = NewLimiterManager()

func join2(c *gin.Context) {

	ip := c.RemoteIP()
	if !limiterManager.Allow(ip) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Too Many Requests"})
		return
	}

	d := c.MustGet("supervisor").(*Supervisor)
	var req message.JoinReq2
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body"})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	if req.RandomStr == "" {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Invalid request body: RandomStr is null"})
		return
	}
	if !VerifySignature(req.PublicKey, req.RandomStr, req.Sign1, req.Sign2) {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid sign."})
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
			c.JSON(http.StatusOK, gin.H{"error": "Join failed, try again later..."})
			return
		}
	}

	var nodes []Node
	countN := 0
	db.DB.Model(Node{}).Where("ip = ?", ip).Find(&nodes)
	if len(nodes) > 0 {
		for _, node := range nodes {
			if time.Since(node.Beattime).Seconds() < 120 {
				countN++
			}
		}
	}

	var cMaxNodePerIp Config
	if e := db.DB.Model(cMaxNodePerIp).Where("config = ?", "max_node_num_per_ip").Find(&cMaxNodePerIp).Error; e != nil {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		return
	}
	cMaxNodePerIpVal, _ := strconv.Atoi(cMaxNodePerIp.Value)

	if countN >= cMaxNodePerIpVal {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Can not launch too many nodes."})
		return
	}

	var pnodes []PendingNode
	db.DB.Model(PendingNode{}).Where("ip = ?", ip).Find(&pnodes)
	if len(pnodes) > 0 {
		for _, node := range pnodes {
			if time.Since(node.Beattime).Seconds() < 120 {
				countN++
			}
		}
	}
	if countN >= cMaxNodePerIpVal {
		c.JSON(http.StatusOK, gin.H{"error": "Failed. Can not launch too many nodes."})
		return
	}

	Lock.Lock()
	defer Lock.Unlock()

	d.Lock.Lock()
	defer d.Lock.Unlock()

	tx := db.DB.Begin()

	var admission Admission
	if tx.Model(admission).Where("addr = ?", addr).Find(&admission).Error != nil {
		unit := new(big.Int)
		unit.SetString(global.Uint, 10)
		var cc Config
		if e := tx.Model(cc).Where("config = ?", "ticket").Find(&cc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
		ticket := new(big.Int)
		ticket.SetString(cc.Value, 10)
		ticket.Mul(ticket, unit)
		var acc Account
		if e := tx.Model(acc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", addr).Find(&acc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
			return
		}
		balancebi := new(big.Int)
		balance := acc.Value
		if strings.Contains(acc.Value, ".") {
			balance = strings.Split(acc.Value, ".")[0]
		}
		balancebi.SetString(balance, 10)
		if balancebi.Cmp(ticket) < 0 {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Your balance is less than " + cc.Value + " BKC."})
			return
		}
		balancebi.Sub(balancebi, ticket)
		acc.Value = balancebi.String()
		acc.Version = acc.Version + 1
		if e := tx.Model(acc).Where("id = ?", acc.Id).Update(&acc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
			return
		}
		var TX_ TX3
		TX_.From = acc.Addr
		TX_.To = "9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1"
		TX_.Value = ticket.String()
		TX_.Timestamp = time.Now()
		TX_.Fee = "0"
		if e := tx.Model(TX_).Create(&TX_).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
			return
		}
		admission.Addr = acc.Addr
		if e := tx.Model(admission).Create(&admission).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
			return
		}
		var superacc Account
		if e := tx.Model(superacc).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", "9a44d9d823ca62ee8b89cdfd4d2bf56b56f16ab1").Find(&superacc).Error; e != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
			return
		}
		superaccbalance := new(big.Int)
		_, ok := superaccbalance.SetString(superacc.Value, 10)
		if ok {
			superaccbalance.Add(superaccbalance, ticket)
			superacc.Value = superaccbalance.String()
			superacc.Version = superacc.Version + 1
			if e := tx.Model(superacc).Where("id = ?", superacc.Id).Update(&superacc).Error; e != nil {
				tx.Rollback()
				c.JSON(http.StatusOK, gin.H{"error": "Join failed. Try again later"})
				return
			}
		}
	}
	tx.Commit()

	//a := atomic.Bool{}
	//wg := sync.WaitGroup{}
	//wg.Add(1)
	//go func() {
	//	ConnectionMapLock.RLock()
	//	defer ConnectionMapLock.RUnlock()
	//	defer wg.Done()
	//	for k, v := range CMap {
	//		if v == addr {
	//			conn,ok := ConnectionMap[k]
	//			if ok {
	//				msg := message.MergeMessage(message.CPing, []byte(""))
	//				_, err := conn.Write(msg)
	//				if err == nil {
	//					a.Store(true)
	//					return
	//				}
	//				//if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 == nil {
	//				//a.Store(true)
	//				//return
	//				//}
	//			}
	//		}
	//	}
	//}()
	//
	//wg.Wait()
	//if a.Load(){
	//	//c.JSON(http.StatusOK, gin.H{"error": "do not join system using the same private key"})
	//	//return
	//}

	host, port, _ := net.SplitHostPort(strings.TrimSpace(c.Request.RemoteAddr))

	tx = db.DB.Begin()
	var checkNode PendingNode
	if tx.Model(checkNode).Where("publickey = ?", addr).Find(&checkNode).Error != nil {
		//tx.Rollback()
		//c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
		//return
		n := PendingNode{
			PublicKey: addr,
			Ip:        host,
			Port:      port,
			Beattime:  time.Now(),
		}
		if err := tx.Model(&n).Create(&n).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
	}
	var cc Config
	db.DB.Model(cc).Where("config = ?", "shardid").Find(&cc)
	shardNum, _ := strconv.Atoi(cc.Value)
	rand.Seed(time.Now().UnixNano())
	intn := rand.Intn(shardNum)
	var loc Location
	if tx.Model(loc).Where("addr = ?", addr).Find(&loc).Error != nil {
		loc.Location = uint64(intn)
		loc.Addr = addr
		if err := tx.Model(loc).Create(&loc).Error; err != nil {
			tx.Rollback()
			c.JSON(http.StatusOK, gin.H{"error": "Failed. Try again later"})
			return
		}
	}

	tx.Commit()

	c.JSON(http.StatusOK, gin.H{"message": "success"})
}
func check2(arr [32]byte, arr2 [32]byte, difficulty int) bool {
	count := 0
	for i := 0; i < 32 && count < difficulty; i++ {
		for j := 0; j < 8 && count < difficulty; j++ {
			if (arr[i] & (1 << (7 - j))) != (arr2[i] & (1 << (7 - j))) {
				return false
			} else {
				count++
			}
		}
	}
	return true
}
func convertTo32ByteArray(input []byte) [32]byte {
	var result [32]byte
	copy(result[:], input)
	return result
}

var juniormincache int
var juniormintime time.Time
var seniormmincache int
var seniormintime time.Time
var mu1 sync.Mutex
var mu2 sync.Mutex

func getminjunior() int {
	mu1.Lock()
	defer mu1.Unlock()
	if juniormintime.Add(time.Second * 30).After(time.Now()) {
		return juniormincache
	}
	juniormintime = time.Now()
	var results []NodeCount
	var cc1 Config
	db.DB.Model(cc1).Where("config = ? ", "nodepershard").Find(&cc1)
	nodepershard, _ := strconv.Atoi(cc1.Value)
	nodepershard = nodepershard * 2 / 3
	err := db.DB.Raw("SELECT shardid, COUNT(*) as count FROM nodes WHERE TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 GROUP BY shardid having count(*) > " + strconv.Itoa(nodepershard) + " ORDER BY shardid ASC").Scan(&results).Error
	if err != nil {
		juniormincache = 34602
		return juniormincache
	}
	if len(results) == 0 {
		juniormincache = 34602
		return juniormincache
	}
	juniormincache, _ = strconv.Atoi(results[0].ShardID)
	return juniormincache
}

func getminsenior() int {
	mu2.Lock()
	defer mu2.Unlock()
	if seniormintime.Add(time.Second * 30).After(time.Now()) {
		return seniormmincache
	}
	seniormintime = time.Now()
	var cc1 Config
	var results []NodeCount
	db.DB.Model(cc1).Where("config = ? ", "nodepershard_senior").Find(&cc1)
	nodepershard, _ := strconv.Atoi(cc1.Value)
	nodepershard = nodepershard * 2 / 3
	err := db.DB.Raw("SELECT shardid, COUNT(*) as count FROM nodes2 WHERE TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 GROUP BY shardid having count(*) > " + strconv.Itoa(nodepershard) + " ORDER BY shardid ASC").Scan(&results).Error
	if err != nil {
		seniormmincache = 609
		return seniormmincache
	}
	if len(results) == 0 {
		seniormmincache = 609
		return seniormmincache
	}
	seniormmincache, _ = strconv.Atoi(results[0].ShardID)
	return seniormmincache
}

func reportblock(c *gin.Context) {
	ip := c.RemoteIP()
	limiter := getOrNewRateLimiter(ip)
	for _, l := range limiter.limiters {
		if !l.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error": "too many requests",
			})
			fmt.Println("too many requests")
			return
		}
	}

	var req message.ReportBlockReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.Root + req.IsLeader
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
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}

	//var Calpha Config
	//db.DB.Where("config = ?", "alpha").Find(&Calpha)
	//var Cbeta Config
	//db.DB.Where("config = ?", "beta").Find(&Cbeta)
	//var Cgamma Config
	//db.DB.Where("config = ?", "gamma").Find(&Cgamma)
	//var Cdelta Config
	//db.DB.Where("config = ?", "delta").Find(&Cdelta)
	//var Crho Config
	//db.DB.Where("config = ?", "rho").Find(&Crho)
	//var Ctheta Config
	//db.DB.Where("config = ?", "theta").Find(&Ctheta)
	//var CT_0 Config
	//db.DB.Where("config = ?", "T_0").Find(&CT_0)

	//alpha := Calpha.Value
	//beta := Cbeta.Value
	//gamma := Cgamma.Value
	//delta := Cdelta.Value
	//rho := Crho.Value
	//theta := Ctheta.Value
	//T_0 := CT_0.Value

	//var node Node
	//db.DB.Model(node).Where("publickey = ?", addr).Find(&node)
	//T_online := strconv.Itoa(int(time.Since(node.Timestamp).Seconds()))
	//n_shard := "4"
	//V_h := "1"
	//R_h := ""
	//if req.IsLeader == "true" {
	//	R_h = "1"
	//} else {
	//	R_h = rho
	//}

	//alphaF, _ := new(big.Float).SetString(alpha)
	//betaF, _ := new(big.Float).SetString(beta)
	//gammaF, _ := new(big.Float).SetString(gamma)
	//deltaF, _ := new(big.Float).SetString(delta)
	////rhoF,_:=new(big.Float).SetString(rho)
	//thetaF, _ := new(big.Float).SetString(theta)
	//T_0F, _ := new(big.Float).SetString(T_0)
	//R_hF, _ := new(big.Float).SetString(R_h)
	//T_onlineF, _ := new(big.Float).SetString(T_online)
	//n_shardF, _ := new(big.Float).SetString(n_shard)
	//V_hF, _ := new(big.Float).SetString(V_h)

	//CoinBase := new(big.Float)
	//Cterm1 := new(big.Float)
	//Cterm1.Mul(alphaF, R_hF)
	//Cterm2 := new(big.Float)
	//Cterm2.Mul(betaF, V_hF)
	//Cterm3 := new(big.Float)
	//Cterm3.Quo(gammaF, n_shardF.Add(n_shardF, deltaF))
	//CoinBase.Add(Cterm1, Cterm2)
	//CoinBase.Add(CoinBase, Cterm3)

	//One := new(big.Float)
	//One.SetString("1")
	//
	//Iterm := new(big.Float)
	//Iterm.Quo(T_onlineF, T_0F)
	//Iterm.Add(Iterm, One)
	//IncentiveLn := bigfloat.Log(Iterm)
	//Incentive := new(big.Float)
	//Incentive.Mul(IncentiveLn, thetaF)
	//
	//Reward := new(big.Float)
	//Reward.Add(CoinBase, Incentive)
	//
	//unit := new(big.Float)
	//unit.SetString(global.Uint)
	//
	//bf0 := new(big.Float)
	//bf0.Mul(Reward, unit)
	//
	//var intResult big.Int
	//bf0.Int(&intResult)

	//bf0.SetInt(&intResult)
	//
	//bf0.SetString("0")

	F := new(big.Float)
	F.SetString("0")
	//if req.Txs != nil && len(req.Txs) > 0 {
	//	for _, tx := range req.Txs {
	//		if tx.Fee != nil {
	//			bf1 := new(big.Float)
	//			bf1.SetInt(tx.Fee)
	//			bf2 := new(big.Float)
	//			if tx.Flag1 && tx.Flag2 {
	//				bf2.SetString("0.9")
	//			} else {
	//				bf2.SetString("0.45") //0.9*0.5
	//			}
	//			bf1.Mul(bf1, bf2)
	//			F.Add(F, bf1)
	//		}
	//	}
	//}
	fmt.Println("F:" + F.String())
	var B_0_config Config
	db.DB.Where("config = ?", "B_0").Find(&B_0_config)
	B_0 := new(big.Float)
	B_0.SetString(B_0_config.Value)

	var T_config Config
	db.DB.Where("config = ?", "T").Find(&T_config)
	T := new(big.Float)
	T.SetString(T_config.Value)

	var CreationConfig Config
	db.DB.Model(CreationConfig).Where("config = ?", "Creation").Find(&CreationConfig)
	t_0 := new(big.Float)
	t_0.SetString(CreationConfig.Value)

	now := strconv.FormatInt(time.Now().UnixMilli(), 10)
	beta_s_h := new(big.Float)
	beta_s_h.SetString(now)
	beta_s_h.Sub(beta_s_h, t_0)
	fmt.Println("beta_s_h:" + beta_s_h.String())
	beta_s_h.Quo(beta_s_h, T)
	fmt.Println("T:" + T.String())
	fmt.Println("beta_s_h:" + beta_s_h.String())

	//round := new(big.Int)
	//beta_s_h.Int(round) //TODO
	//beta_s_h.SetInt(round)
	fmt.Println("beta_s_h:" + beta_s_h.String())

	f, _ := beta_s_h.Float64()
	fmt.Println("f:" + strconv.FormatFloat(f, 'f', 2, 64))
	pow := math.Pow(2, f)

	powbf := new(big.Float).SetFloat64(pow)
	fmt.Println("powbf:" + powbf.String())
	one := new(big.Float)
	one.SetString("1")
	one.Quo(one, powbf)
	fmt.Println("one:" + one.String())

	B_0.Mul(B_0, one)
	fmt.Println("B_0:" + B_0.String())

	var ss Config
	var ss2 Config
	db.DB.Model(ss).Where("config = ?", "shardid").Find(&ss)
	shardNum, _ := strconv.Atoi(ss.Value)
	validShard := 0
	db.DB.Model(ss2).Where("config = ?", "shardid_senior").Find(&ss2)
	shardNum2, _ := strconv.Atoi(ss2.Value)
	for i := getminsenior(); i < shardNum2; i++ {
		var b1 Block2
		db.DB.Model(b1).Where("shard_id = ?", i).Order("timestamp desc").Order("id desc").First(&b1)

		if time.Since(b1.Timestamp).Seconds() < 60 {
			validShard = validShard + 5
		}

		//var ns []Node
		//if e := db.DB.Model(Node{}).Where("shardid = ?", strconv.Itoa(i)).Find(&ns).Error; e != nil {
		//	continue
		//}
		//count := 0
		//for _, n := range ns {
		//	if time.Since(n.Beattime).Seconds() <= 10 {
		//		count++
		//	}
		//}
		//if count > len(ns)*2/3 {
		//	validShard++
		//}
	}
	for i := getminjunior(); i < shardNum; i++ {
		var b1 Block
		db.DB.Model(b1).Where("shard_id = ?", i).Order("timestamp desc").Order("id desc").First(&b1)

		if time.Since(b1.Timestamp).Seconds() < 60 {
			validShard++
		}

		//var ns []Node
		//if e := db.DB.Model(Node{}).Where("shardid = ?", strconv.Itoa(i)).Find(&ns).Error; e != nil {
		//	continue
		//}
		//count := 0
		//for _, n := range ns {
		//	if time.Since(n.Beattime).Seconds() <= 10 {
		//		count++
		//	}
		//}
		//if count > len(ns)*2/3 {
		//	validShard++
		//}
	}
	if validShard == 0 {
		validShard = 1
	}

	validShardbf := new(big.Float)
	validShardbf.SetInt64(int64(validShard))
	fmt.Println("B_0:" + B_0.String())
	B_0.Quo(B_0, validShardbf)
	fmt.Println("B_0:" + B_0.String())
	R := new(big.Float)
	R.Add(B_0, F)
	fmt.Println("R:" + R.String())

	mm1 := make(map[string]*big.Float)
	//mm1[addr] = new(big.Float).SetInt64(10)
	S := new(big.Float)
	//S.Add(S, new(big.Float).SetInt64(10))
	//fmt.Println("S:" + S.String())

	if req.BlockHash == nil || len(req.BlockHash) == 0 {
		c.JSON(http.StatusOK, gin.H{"message": "success", "id": 3})
		return
	}
	hash := req.BlockHash

	if req.Signs != nil && len(req.Signs) > 0 {
		for idx, s := range req.Signs {
			if idx < len(req.Signs2) {
				s2 := req.Signs2[idx]
				s3 := string(hash) + s2

				arr1 := sha256.Sum256([]byte(s3))
				if check2(arr1, convertTo32ByteArray(hash), 22) {
					fmt.Println("验证成功:" + s2)
				} else {
					continue
				}
			} else {
				continue
			}
			split := strings.Split(s, ":")
			sharId := split[0]
			nodeId := split[1]
			var n Node
			db.DB.Model(n).Where("shardid = ? and nodeid = ?", sharId, nodeId).Find(&n)
			if n.Id != 0 {
				phi := new(big.Float)
				detlat := time.Since(n.Timestamp).Milliseconds()
				H := int64(3600000)
				if detlat >= H*256 {
					phi = new(big.Float).SetInt64(9)
				} else if detlat < H*256 && detlat >= H*128 {
					phi = new(big.Float).SetInt64(8)
				} else if detlat < H*128 && detlat >= H*64 {
					phi = new(big.Float).SetInt64(7)
				} else if detlat < H*64 && detlat >= H*32 {
					phi = new(big.Float).SetInt64(6)
				} else if detlat < H*32 && detlat >= H*16 {
					phi = new(big.Float).SetInt64(5)
				} else if detlat < H*16 && detlat >= H*8 {
					phi = new(big.Float).SetInt64(4)
				} else if detlat < H*8 && detlat >= H*4 {
					phi = new(big.Float).SetInt64(3)
				} else if detlat < H*4 && detlat >= H*2 {
					phi = new(big.Float).SetInt64(2)
				} else if detlat < H*2 && detlat >= H*1 {
					phi = new(big.Float).SetInt64(1)
				} else {
					phi, _ = new(big.Float).SetString("0.1")
				}
				if n.PublicKey != addr {
					mm1[n.PublicKey] = phi
					S.Add(S, phi)
					fmt.Println("S:" + S.String())
				} else {
					phi.Mul(phi, new(big.Float).SetInt64(2))
					mm1[n.PublicKey] = phi
					S.Add(S, phi)
					fmt.Println("S:" + S.String())
				}
			}
		}
	}

	for k, v := range mm1 {
		aa := new(big.Float)
		aa.Quo(v, S)
		fmt.Println("aa:" + aa.String())
		Reward1 := new(big.Float)
		Reward1.Mul(aa, R)
		fmt.Println("Reward1:" + Reward1.String())

		unit := new(big.Float)
		unit.SetString(global.Uint)
		Reward1.Mul(unit, Reward1)

		g := new(big.Int)
		Reward1.Int(g)
		Reward1.SetInt(g)
		fmt.Println("Reward1:" + Reward1.String())
		var ac Account
		Tr := db.DB.Begin()
		if e := Tr.Model(ac).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", k).Find(&ac).Error; e != nil {
			Tr.Rollback()
			continue
		}
		bf1 := new(big.Float)
		bf1.SetString(ac.Value)
		bf1.Add(bf1, Reward1)
		ac.Value = bf1.Text('f', -1)
		if e := Tr.Model(ac).Where("id = ? ", ac.Id).Update(&ac).Error; e != nil {
			Tr.Rollback()
			continue
		}

		tx2 := TX2{
			From:      global.SuperAcc,
			To:        ac.Addr,
			Value:     Reward1.Text('f', -1),
			Timestamp: time.Now(),
			Type:      "junior",
		}
		if e := Tr.Model(tx2).Create(&tx2).Error; e != nil {
			Tr.Rollback()
			continue
		}
		//d := c.MustGet("supervisor").(*Supervisor)
		//go func() {
		//	defer func() {
		//		if err := recover(); err != nil {
		//			fmt.Println(err)
		//		}
		//	}()
		//	//d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: tx2.From}, partition.Vertex{Addr: tx2.To})
		//}()
		Tr.Commit()
	}

	var b Block
	b.Timestamp = time.Now()
	b.ShardId = req.ShardId
	b.Addr = GetAddress(req.PublicKey)
	b.Hash = hex.EncodeToString(req.BlockHash)
	b.PreHash = hex.EncodeToString(req.PreBlockHash)
	b.Signs1 = strings.Join(req.Signs, ";")
	b.Signs2 = strings.Join(req.Signs2, ";")
	if e := db.DB.Model(b).Create(&b).Error; e != nil {
		fmt.Println(e)
	}

	//Lock.Lock()
	//defer Lock.Unlock()
	//var acc1 Account
	//if err := db.DB.Model(acc1).Where("addr = ?", addr).Find(&acc1).Error; err != nil {
	//	c.JSON(http.StatusOK, gin.H{"message": "success"})
	//	return
	//}
	//fmt.Println("handle report block : ", addr)
	//
	//var nodes []Node
	//signs := req.Signs
	//for _, s := range signs {
	//	split := strings.Split(s, ":")
	//	sharId := split[0]
	//	nodeId := split[1]
	//	var node1 Node
	//	db.DB.Model(node1).Where("shardid = ? and nodeid = ? ", sharId, nodeId).Find(&node1)
	//	if node1.Id != 0 {
	//		nodes = append(nodes, node1)
	//	}
	//}
	//var accounts []string
	//for _, n := range nodes {
	//	accounts = append(accounts, n.PublicKey)
	//}
	//
	//for _, acc := range accounts {
	//	var a Account
	//	db.DB.Model(a).Where("addr = ?", acc).Find(&a)
	//	if a.Id != 0 {
	//		bf1 := new(big.Float)
	//		bf1.SetString(a.Value)
	//		bf1.Add(bf1, bf0)
	//		a.Value = bf1.Text('f', -1)
	//		db.DB.Model(a).Where("id = ?", a.Id).Update(&a)
	//	}
	//}

	//tx := db.DB.Begin()
	//var block Block
	//var block2 Block
	//var count int64
	//if e := tx.Model(&Block{}).
	//	Where("addr = ?", addr).
	//	Count(&count).Error; e != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 1})
	//	return
	//}

	//if count == 0 {
	//	block2.Addr = addr
	//	block2.Timestamp = time.Now()
	//	if e := tx.Model(block2).Create(&block2).Error; e != nil {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"message": "success", "id": 2})
	//		return
	//	}
	//	//unit := new(big.Float)
	//	//unit.SetString(global.Uint)
	//	//加钱
	//	//reward := GetReward(count)
	//	//bf0 := new(big.Float)
	//	//
	//	//bf0.SetFloat64(reward)
	//	//bf0.Mul(bf0, unit)
	//	bf := new(big.Float)
	//	bf.SetPrec(512)
	//	_, _ = bf.SetString(acc1.Value)
	//
	//	bff := new(big.Float)
	//	bff.SetPrec(512)
	//	bff.Add(bf, bf0)
	//
	//	flag := false
	//	count1 := 0
	//	for {
	//		count1++
	//		if count1 > 10 {
	//			break
	//		}
	//		acc1.Value = bff.Text('f', -1)
	//		res1 := tx.Model(Account{}).
	//			Where("id = ? AND version = ?", acc1.Id, acc1.Version).
	//			Updates(map[string]interface{}{
	//				"balance": acc1.Value,
	//				"version": acc1.Version + 1,
	//			})
	//
	//		if res1.Error != nil {
	//			tx.Rollback()
	//			c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again."})
	//			return
	//		}
	//
	//		// 检查是否成功更新了记录
	//		if res1.RowsAffected > 0 {
	//			flag = true
	//			break
	//		}
	//		time.Sleep(100 * time.Millisecond)
	//		tx.Model(acc1).Where("addr = ?", addr).Find(&acc1)
	//	}
	//
	//	if !flag {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 3})
	//		return
	//	}
	//
	//	var acc2 Account
	//	tx.Model(acc2).Where("addr = ?", global.SuperAcc).Find(&acc2)
	//	flag2 := false
	//	count2 := 0
	//	bff2 := new(big.Float)
	//	bff2.SetPrec(512)
	//	bf2 := new(big.Float)
	//	bf2.SetPrec(512)
	//	bf2.SetString(acc2.Value)
	//	if bf2.Signbit() {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. No reward token is available.", "id": 8})
	//		return
	//	}
	//	for {
	//		count2++
	//		if count2 > 10 {
	//			break
	//		}
	//		bff2.Sub(bf2, bf0)
	//		acc2.Value = bff2.Text('f', -1)
	//		res1 := tx.Model(Account{}).
	//			Where("id = ? AND version = ?", acc2.Id, acc2.Version).
	//			Updates(map[string]interface{}{
	//				"balance": acc2.Value,
	//				"version": acc2.Version + 1,
	//			})
	//
	//		if res1.Error != nil {
	//			tx.Rollback()
	//			c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 6})
	//			return
	//		}
	//
	//		// 检查是否成功更新了记录
	//		if res1.RowsAffected > 0 {
	//			flag2 = true
	//			break
	//		}
	//		time.Sleep(100 * time.Millisecond)
	//		tx.Model(acc2).Where("addr = ?", global.SuperAcc).Find(&acc2)
	//		bf2.SetString(acc2.Value)
	//	}
	//	if !flag2 {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 7})
	//		return
	//	}
	//
	//	tx2 := TX2{
	//		From:      global.SuperAcc,
	//		To:        acc1.Addr,
	//		Value:     bf0.Text('f', -1),
	//		Timestamp: time.Now(),
	//	}
	//	if e := tx.Model(tx2).Create(&tx2).Error; e != nil {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 3})
	//		return
	//	}
	//
	//	tx.Commit()
	//	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 3})
	//
	//	return
	//}

	//if e := tx.Model(block).Where("addr = ?", addr).Order("timestamp DESC").First(&block).Error; e != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 4})
	//	return
	//}
	//
	//if time.Since(block.Timestamp).Seconds() < 3 {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 5})
	//	return
	//}
	//
	//block2.Addr = addr
	//block2.Timestamp = time.Now()
	//if e := tx.Model(block2).Create(&block2).Error; e != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 2})
	//	return
	//}
	////加钱
	////reward := GetReward(count)
	////
	////unit := new(big.Float)
	////unit.SetString(global.Uint)
	////bf0 := new(big.Float)
	////bf0.SetFloat64(reward)
	////bf0.Mul(bf0, unit)
	//bf := new(big.Float)
	//bf.SetPrec(512)
	//_, _ = bf.SetString(acc1.Value)
	//
	//bff := new(big.Float)
	//bff.SetPrec(512)
	////bff.Add(bf, bf0)
	//
	//flag := false
	//count1 := 0
	//for {
	//	count1++
	//	if count1 > 10 {
	//		break
	//	}
	//	bff = new(big.Float)
	//	bff.Add(bf, bf0)
	//	acc1.Value = bff.Text('f', -1)
	//	res1 := tx.Model(Account{}).
	//		Where("id = ? AND version = ?", acc1.Id, acc1.Version).
	//		Updates(map[string]interface{}{
	//			"balance": acc1.Value,
	//			"version": acc1.Version + 1,
	//		})
	//
	//	if res1.Error != nil {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 6})
	//		return
	//	}
	//
	//	// 检查是否成功更新了记录
	//	if res1.RowsAffected > 0 {
	//		flag = true
	//		break
	//	}
	//	time.Sleep(100 * time.Millisecond)
	//	tx.Model(acc1).Where("addr = ?", addr).Find(&acc1)
	//	bf.SetString(acc1.Value)
	//}
	//
	//if !flag {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 7})
	//	return
	//}
	//var acc2 Account
	//tx.Model(acc2).Where("addr = ?", global.SuperAcc).Find(&acc2)
	//flag2 := false
	//count2 := 0
	//bff2 := new(big.Float)
	//bff2.SetPrec(512)
	//bf2 := new(big.Float)
	//bf2.SetPrec(512)
	//bf2.SetString(acc2.Value)
	//if bf2.Signbit() {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. No reward token is available.", "id": 8})
	//	return
	//}
	//for {
	//	count2++
	//	if count2 > 10 {
	//		break
	//	}
	//	bff2.Sub(bf2, bf0)
	//	acc2.Value = bff2.Text('f', -1)
	//	res1 := tx.Model(Account{}).
	//		Where("id = ? AND version = ?", acc2.Id, acc2.Version).
	//		Updates(map[string]interface{}{
	//			"balance": acc2.Value,
	//			"version": acc2.Version + 1,
	//		})
	//
	//	if res1.Error != nil {
	//		tx.Rollback()
	//		c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 6})
	//		return
	//	}
	//
	//	// 检查是否成功更新了记录
	//	if res1.RowsAffected > 0 {
	//		flag2 = true
	//		break
	//	}
	//	time.Sleep(100 * time.Millisecond)
	//	tx.Model(acc2).Where("addr = ?", global.SuperAcc).Find(&acc2)
	//	bf2.SetString(acc2.Value)
	//}
	//if !flag2 {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 7})
	//	return
	//}
	//
	//tx2 := TX2{
	//	From:      global.SuperAcc,
	//	To:        acc1.Addr,
	//	Value:     bf0.Text('f', -1),
	//	Timestamp: time.Now(),
	//}
	//if e := tx.Model(tx2).Create(&tx2).Error; e != nil {
	//	tx.Rollback()
	//	c.JSON(http.StatusOK, gin.H{"error": "Failed. Please try again.", "id": 3})
	//	return
	//}
	//
	//tx.Commit()
	//d := c.MustGet("supervisor").(*Supervisor)
	//d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.AddEdge(partition.Vertex{Addr: tx2.From}, partition.Vertex{Addr: tx2.To})

	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 3})

	//c.JSON(http.StatusOK, gin.H{"message": "success", "id": 6})
	return
}

func reportblock_senior(c *gin.Context) {
	ip := c.RemoteIP()
	limiter := getOrNewRateLimiter(ip)
	for _, l := range limiter.limiters {
		if !l.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error": "too many requests",
			})
			fmt.Println("too many requests")
			return
		}
	}

	var req message.ReportBlockReq
	if err := c.ShouldBind(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"error": err.Error()})
		return
	}
	if req.PublicKey == "" {
		c.JSON(http.StatusOK, gin.H{"message": "Failed. Invalid request body: PublicKey is null"})
		return
	}
	thedata := req.RandomStr + req.Root + req.IsLeader
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
		c.JSON(http.StatusOK, gin.H{"error": "addr not exist"})
		return
	}

	F := new(big.Float)
	F.SetString("0")
	fmt.Println("F:" + F.String())
	var B_0_config Config
	//db.DB.Where("config = ?", "B_0_senior").Find(&B_0_config)
	db.DB.Where("config = ?", "B_0").Find(&B_0_config)
	B_0 := new(big.Float)
	B_0.SetString(B_0_config.Value)

	var T_config Config
	db.DB.Where("config = ?", "T").Find(&T_config)
	T := new(big.Float)
	T.SetString(T_config.Value)

	var CreationConfig Config
	db.DB.Model(CreationConfig).Where("config = ?", "Creation").Find(&CreationConfig)
	t_0 := new(big.Float)
	t_0.SetString(CreationConfig.Value)

	now := strconv.FormatInt(time.Now().UnixMilli(), 10)
	beta_s_h := new(big.Float)
	beta_s_h.SetString(now)
	beta_s_h.Sub(beta_s_h, t_0)
	fmt.Println("beta_s_h:" + beta_s_h.String())
	beta_s_h.Quo(beta_s_h, T)
	fmt.Println("T:" + T.String())
	fmt.Println("beta_s_h:" + beta_s_h.String())

	fmt.Println("beta_s_h:" + beta_s_h.String())

	f, _ := beta_s_h.Float64()
	fmt.Println("f:" + strconv.FormatFloat(f, 'f', 2, 64))
	pow := math.Pow(2, f)

	powbf := new(big.Float).SetFloat64(pow)
	fmt.Println("powbf:" + powbf.String())
	one := new(big.Float)
	one.SetString("1")
	one.Quo(one, powbf)
	fmt.Println("one:" + one.String())

	B_0.Mul(B_0, one)
	fmt.Println("B_0:" + B_0.String())

	var ss Config
	var ss2 Config
	db.DB.Model(ss).Where("config = ?", "shardid_senior").Find(&ss)
	shardNum, _ := strconv.Atoi(ss.Value)
	db.DB.Model(ss2).Where("config = ?", "shardid").Find(&ss2)
	shardNum2, _ := strconv.Atoi(ss2.Value)
	validShard := 0
	for i := getminjunior(); i < shardNum2; i++ {
		var b1 Block
		db.DB.Model(b1).Where("shard_id = ?", i).Order("timestamp desc").Order("id desc").First(&b1)

		if time.Since(b1.Timestamp).Seconds() < 60 {
			validShard++
		}

		//var ns []Node
		//if e := db.DB.Model(Node{}).Where("shardid = ?", strconv.Itoa(i)).Find(&ns).Error; e != nil {
		//	continue
		//}
		//count := 0
		//for _, n := range ns {
		//	if time.Since(n.Beattime).Seconds() <= 10 {
		//		count++
		//	}
		//}
		//if count > len(ns)*2/3 {
		//	validShard++
		//}
	}

	for i := getminsenior(); i < shardNum; i++ {
		var b1 Block2
		db.DB.Model(b1).Where("shard_id = ?", i).Order("timestamp desc").Order("id desc").First(&b1)

		if time.Since(b1.Timestamp).Seconds() < 60 {
			validShard = validShard + 5
		}
	}
	if validShard == 0 {
		validShard = 1
	}

	validShardbf := new(big.Float)
	validShardbf.SetInt64(int64(validShard))
	fmt.Println("B_0:" + B_0.String())
	B_0.Quo(B_0, validShardbf)
	ten := new(big.Float)
	ten.SetString("5")
	B_0.Mul(B_0, ten)
	fmt.Println("B_0:" + B_0.String())
	R := new(big.Float)
	R.Add(B_0, F)
	fmt.Println("R:" + R.String())

	mm1 := make(map[string]*big.Float)
	//mm1[addr] = new(big.Float).SetInt64(10)
	S := new(big.Float)
	//S.Add(S, new(big.Float).SetInt64(10))
	//fmt.Println("S:" + S.String())

	if req.BlockHash == nil || len(req.BlockHash) == 0 {
		c.JSON(http.StatusOK, gin.H{"message": "success", "id": 3})
		return
	}
	//hash := req.BlockHash

	if req.Signs != nil && len(req.Signs) > 0 {
		//for idx, s := range req.Signs {
		for _, s := range req.Signs {
			//if idx < len(req.Signs2){
			//	//s2 := req.Signs2[idx]
			//	//s3 := string(hash) + s2
			//
			//	//arr1 := sha256.Sum256([]byte(s3))
			//	//if check2(arr1,convertTo32ByteArray(hash),2) {
			//	//	fmt.Println("验证成功:"+s2)
			//	//}else {
			//	//	continue
			//	//}
			//} else {
			//	continue
			//}
			split := strings.Split(s, ":")
			sharId := split[0]
			nodeId := split[1]
			var n Node2
			db.DB.Model(n).Where("shardid = ? and nodeid = ?", sharId, nodeId).Find(&n)
			if n.Id != 0 {
				phi := new(big.Float)
				detlat := time.Since(n.Timestamp).Milliseconds()
				H := int64(3600000)
				if detlat >= H*256 {
					phi = new(big.Float).SetInt64(9)
				} else if detlat < H*256 && detlat >= H*128 {
					phi = new(big.Float).SetInt64(8)
				} else if detlat < H*128 && detlat >= H*64 {
					phi = new(big.Float).SetInt64(7)
				} else if detlat < H*64 && detlat >= H*32 {
					phi = new(big.Float).SetInt64(6)
				} else if detlat < H*32 && detlat >= H*16 {
					phi = new(big.Float).SetInt64(5)
				} else if detlat < H*16 && detlat >= H*8 {
					phi = new(big.Float).SetInt64(4)
				} else if detlat < H*8 && detlat >= H*4 {
					phi = new(big.Float).SetInt64(3)
				} else if detlat < H*4 && detlat >= H*2 {
					phi = new(big.Float).SetInt64(2)
				} else if detlat < H*2 && detlat >= H*1 {
					phi = new(big.Float).SetInt64(1)
				} else {
					phi, _ = new(big.Float).SetString("0.1")
				}
				if n.PublicKey != addr {
					mm1[n.PublicKey] = phi
					S.Add(S, phi)
					fmt.Println("S:" + S.String())
				} else {
					phi.Mul(phi, new(big.Float).SetInt64(2))
					mm1[n.PublicKey] = phi
					S.Add(S, phi)
					fmt.Println("S:" + S.String())
				}
			}
		}
	}

	for k, v := range mm1 {
		aa := new(big.Float)
		aa.Quo(v, S)
		fmt.Println("aa:" + aa.String())
		Reward1 := new(big.Float)
		Reward1.Mul(aa, R)
		fmt.Println("Reward1:" + Reward1.String())

		unit := new(big.Float)
		unit.SetString(global.Uint)
		Reward1.Mul(unit, Reward1)

		g := new(big.Int)
		Reward1.Int(g)
		Reward1.SetInt(g)
		fmt.Println("Reward1:" + Reward1.String())
		var ac Account
		Tr := db.DB.Begin()
		if e := Tr.Model(ac).Set("gorm:query_option", "FOR UPDATE").Where("addr = ?", k).Find(&ac).Error; e != nil {
			Tr.Rollback()
			continue
		}
		bf1 := new(big.Float)
		bf1.SetString(ac.Value)
		bf1.Add(bf1, Reward1)
		ac.Value = bf1.Text('f', -1)
		if e := Tr.Model(ac).Where("id = ? ", ac.Id).Update(&ac).Error; e != nil {
			Tr.Rollback()
			continue
		}

		tx2 := TX2{
			From:      global.SuperAcc,
			To:        ac.Addr,
			Value:     Reward1.Text('f', -1),
			Timestamp: time.Now(),
			Type:      "senior",
		}
		if e := Tr.Model(tx2).Create(&tx2).Error; e != nil {
			Tr.Rollback()
			continue
		}

		Tr.Commit()
	}

	var b Block2
	b.Timestamp = time.Now()
	b.ShardId = req.ShardId
	b.Addr = GetAddress(req.PublicKey)
	b.Hash = hex.EncodeToString(req.BlockHash)
	b.PreHash = hex.EncodeToString(req.PreBlockHash)
	b.Signs1 = strings.Join(req.Signs, ";")
	b.Signs2 = strings.Join(req.Signs2, ";")
	if e := db.DB.Model(b).Create(&b).Error; e != nil {
		fmt.Println(e)
	}

	c.JSON(http.StatusOK, gin.H{"message": "success", "id": 3})

	//c.JSON(http.StatusOK, gin.H{"message": "success", "id": 6})
	return
}
