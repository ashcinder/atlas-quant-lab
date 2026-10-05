package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/message"
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"sync"
	"time"
)

var ConnectionMap = make(map[string]net.Conn)
var CMap = make(map[string]string)
var ConnectionMapLock sync.RWMutex
var ConnectionLockMap = make(map[string]*sync.Mutex)

func (d *Supervisor) handleClientRequest2(con net.Conn) {
	defer con.Close()
	defer func() {
		if err := recover(); err != nil {
			fmt.Println(err)
		}
	}()
	clientReader := bufio.NewReader(con)
	//flag := false
	nkey := ""
	Ip1 := con.RemoteAddr().String()

	for {
		clientRequest, err := clientReader.ReadBytes('\n')

		//limiter := getOrNewRateLimiter2(Ip1)
		//if !limiter.limiters.Allow() {
		//	continue
		//}

		switch err {
		case nil:
			addr, content := message.SplitMessage2(clientRequest)
			if addr == "auth" {
				mm := new(ConReq)
				ee := json.Unmarshal(content, mm)
				if ee != nil {
					return
				}
				if mm.PublicKey == "" {
					return
				}
				thedata := mm.RandomStr
				if !VerifySignature(mm.PublicKey, thedata, mm.Sign1, mm.Sign2) {
					return
				}
				if !checkreplay(mm.RandomStr) {
					return
				}
				addr1 := GetAddress(mm.PublicKey)
				var node1 Node
				//var node2 Node2
				//f1:=true
				//f2:=true
				if err := db.DB.Model(node1).Where("publickey = ?", addr1).Find(&node1).Error; err != nil {
					return
				}
				//if err := db.DB.Model(node2).Where("publickey = ?", addr1).Find(&node2).Error; err != nil {
				//	f2 = false
				//}
				//if !f1 && !f2{
				//	return
				//}
				//flag = true
				//if f1 {
				nodeKey := node1.ShardId + ":" + node1.NodeId
				ConnectionMapLock.Lock()
				ConnectionMap[nodeKey] = con
				ConnectionLockMap[nodeKey] = &sync.Mutex{}
				nkey = nodeKey
				CMap[nkey] = addr1
				ConnectionMapLock.Unlock()
				//} else if f2 {
				//	nodeKey := node2.ShardId + ":" + node2.NodeId
				//	ConnectionMapLock.Lock()
				//	ConnectionMap[nodeKey] = con
				//	ConnectionLockMap[nodeKey] = &sync.Mutex{}
				//	nkey = nodeKey
				//	CMap[nkey] = addr1
				//	ConnectionMapLock.Unlock()
				//}

			} else if addr == "auth2" {
				mm := new(ConReq)
				ee := json.Unmarshal(content, mm)
				if ee != nil {
					return
				}
				if mm.PublicKey == "" {
					return
				}
				thedata := mm.RandomStr
				if !VerifySignature(mm.PublicKey, thedata, mm.Sign1, mm.Sign2) {
					return
				}
				if !checkreplay(mm.RandomStr) {
					return
				}
				addr1 := GetAddress(mm.PublicKey)

				var node2 Node2

				if err := db.DB.Model(node2).Where("publickey = ?", addr1).Find(&node2).Error; err != nil {
					return
				}

				//flag = true
				//if f1 {
				//	nodeKey := node1.ShardId + ":" + node1.NodeId
				//	ConnectionMapLock.Lock()
				//	ConnectionMap[nodeKey] = con
				//	ConnectionLockMap[nodeKey] = &sync.Mutex{}
				//	nkey = nodeKey
				//	CMap[nkey] = addr1
				//	ConnectionMapLock.Unlock()
				//} else if f2 {
				//flag = true
				nodeKey := node2.ShardId + ":" + node2.NodeId
				ConnectionMapLock.Lock()
				ConnectionMap[nodeKey] = con
				ConnectionLockMap[nodeKey] = &sync.Mutex{}
				nkey = nodeKey
				CMap[nkey] = addr1
				ConnectionMapLock.Unlock()
				//}

			} else if addr == "beat" {
				//if !flag {
				//	return
				//}
				//if len(content) > 500000 {
				//	break
				//}
				if nkey != "" {
					var node1 Node
					//var node2 Node2
					ConnectionMapLock.RLock()
					addr2, ok := CMap[nkey]
					ConnectionMapLock.RUnlock()
					if ok {
						go func() {
							if err1 := db.DB.Model(node1).Where("publickey = ?", addr2).Find(&node1).Error; err1 != nil {
								return
							}
							node1.Beattime = time.Now()
							db.DB.Model(node1).Where("id = ?", node1.Id).Update(&node1)
						}()
						//go func() {
						//	if err1 := db.DB.Model(node2).Where("publickey = ?", addr2).Find(&node2).Error; err1 != nil {
						//		return
						//	}
						//	node2.Beattime = time.Now()
						//	db.DB.Model(node2).Where("id = ?",node2.Id).Update(&node2)
						//}()
					}
				}
			} else if addr == "beat2" {
				//if !flag {
				//	return
				//}
				//if len(content) > 500000 {
				//	break
				//}
				if nkey != "" {
					//var node1 Node
					var node2 Node2
					ConnectionMapLock.RLock()
					addr2, ok := CMap[nkey]
					ConnectionMapLock.RUnlock()
					if ok {
						//go func() {
						//	if err1 := db.DB.Model(node1).Where("publickey = ?", addr2).Find(&node1).Error; err1 != nil {
						//		return
						//	}
						//	node1.Beattime = time.Now()
						//	db.DB.Model(node1).Where("id = ?",node1.Id).Update(&node1)
						//}()
						go func() {
							if err1 := db.DB.Model(node2).Where("publickey = ?", addr2).Find(&node2).Error; err1 != nil {
								return
							}
							node2.Beattime = time.Now()
							db.DB.Model(node2).Where("id = ?", node2.Id).Update(&node2)
						}()
					}
				}
			} else {
				//if !flag {
				//	return
				//}
				//if len(content) > 500000 {
				//	break
				//}
				ConnectionMapLock.RLock()
				conn1, ok := ConnectionMap[addr]
				mutex, _ := ConnectionLockMap[addr]
				s1 := CMap[nkey]
				s2 := CMap[addr]
				ConnectionMapLock.RUnlock()
				if !ok {
					continue
				}
				if err1 := conn1.(*net.TCPConn).SetKeepAlive(true); err1 != nil {
					continue
				}
				ff := new(Forward)
				ff.FromAddr = s1
				ff.FromKey = nkey
				ff.ToKey = addr
				ff.ToAddr = s2
				ff.Msg = string(content)
				ff.Timestamp = time.Now()
				ff.Len = len(content)
				ff.Ip = Ip1
				//go func() {
				//	db.DB.Model(Forward{}).Create(&ff)
				//}()
				var wg sync.WaitGroup
				wg.Add(1)
				go func() {
					mutex.Lock()
					defer func() {
						mutex.Unlock()
						wg.Done()
					}()
					conn1.Write(content)
				}()
				wg.Wait()
			}

			//d.handleMessage2(clientRequest)

		case io.EOF:
			log.Println("client closed the connection by terminating the process")
			return
		default:
			log.Printf("error: %v\n", err)
			return
		}
	}
}
