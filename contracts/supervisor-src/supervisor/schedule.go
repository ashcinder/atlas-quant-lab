package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/global"
	"blockEmulator/message"
	"blockEmulator/params"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os/exec"

	"github.com/gorilla/websocket"

	"log"
	"math/rand"
	"strconv"
	"time"
)

func (d *Supervisor) Backupdatabase() {
	dbHost := db.GlobalConfig.DBConf.Host
	dbPort := db.GlobalConfig.DBConf.Port
	dbUser := db.GlobalConfig.DBConf.User
	dbPassword := db.GlobalConfig.DBConf.Passwd
	dbName := db.GlobalConfig.DBConf.Database
	backupDir := "/app/database"

	for {
		backupFile := fmt.Sprintf("%s/backup_%s.sql", backupDir, time.Now().Format("2006-01-02 15:04:05"))
		cmd := exec.Command("/usr/bin/mysqldump", fmt.Sprintf("-h%s", dbHost), fmt.Sprintf("-P%d", dbPort), fmt.Sprintf("-u%s", dbUser), fmt.Sprintf("-p%s", dbPassword), dbName, "--result-file="+backupFile)
		err := cmd.Run()
		if err != nil {
			log.Println("备份失败:", err)
			//return
		} else {
			log.Println("备份成功:", backupFile)
		}
		time.Sleep(time.Hour * 1)
	}

}
func (d *Supervisor) OpenShard_senior() {
	for {
		time.Sleep(time.Second * 2)
		var pendingnodes []PendingNode2
		if err := db.DB.Find(&pendingnodes).Error; err != nil {
			fmt.Println(err)
			continue
		}
		var filterednodes []PendingNode2
		for _, node := range pendingnodes {
			if time.Since(node.Beattime).Seconds() < 10 {
				filterednodes = append(filterednodes, node)
			}
		}
		var cc1 Config
		db.DB.Model(cc1).Where("config = ? ", "nodepershard_senior").Find(&cc1)
		nodepershard, _ := strconv.Atoi(cc1.Value)

		if len(filterednodes) < nodepershard {
			continue
		}
		r := rand.New(rand.NewSource(time.Now().UnixNano()))
		for i := range filterednodes {
			// 生成一个随机索引，范围是从i到切片的末尾
			j := r.Intn(i + 1)
			// 交换当前元素和随机选择的元素
			filterednodes[i], filterednodes[j] = filterednodes[j], filterednodes[i]
		}
		var selectednodes = make([]PendingNode2, nodepershard)

		var cc Config
		db.DB.Where("config = ?", "shardid_senior").Find(&cc)
		shardID, _ := strconv.Atoi(cc.Value)
		cc.Value = strconv.Itoa(shardID + 1)

		var ninfos = make([]message.NodeInfo, nodepershard)
		for i := 0; i < nodepershard; i++ {
			selectednodes[i] = filterednodes[i]
			ninfos[i] = message.NodeInfo{
				PublicKey: filterednodes[i].PublicKey,
				Ip:        filterednodes[i].Ip,
				Port:      filterednodes[i].Port,
				ShardID:   strconv.Itoa(shardID),
			}
		}
		//var existnodes []Node
		var oldnodes []message.NodeInfo
		//if err := db.DB.Find(&existnodes).Error; err != nil {
		//	fmt.Println(err)
		//} else {
		//	if len(existnodes) > 0 {
		//		for _, node := range existnodes {
		//			oldnodes = append(oldnodes, message.NodeInfo{
		//				PublicKey: node.PublicKey,
		//				Ip:        node.Ip,
		//				Port:      node.Port,
		//				ShardID:   node.ShardId,
		//			})
		//		}
		//	}
		//}
		oldnodes = append(oldnodes, message.NodeInfo{
			PublicKey: "1",
			Ip:        "1",
			Port:      "1",
			ShardID:   "1",
		})

		var proxys []Proxy
		db.DB.Model(Proxy{}).Find(&proxys)
		r1 := rand.New(rand.NewSource(time.Now().UnixNano()))
		for i := range proxys {
			j := r1.Intn(i + 1)
			proxys[i], proxys[j] = proxys[j], proxys[i]
		}

		//config_ := message.DynamicConfig{NewNodeinfos: ninfos, OldNodeinfos: oldnodes,ProxyIp: proxys[0].IP,ProxyPort: proxys[0].Port,}
		config_ := message.DynamicConfig{NewNodeinfos: ninfos, OldNodeinfos: oldnodes, ProxyIp: global.DomainName, ProxyPort: "56743"}
		bytes, err := json.Marshal(config_)
		if err != nil {
			fmt.Println(err)
		}

		flag1 := true
		for _, node := range selectednodes {
			connectionsLock_senior.Lock()
			_, ok := connections_senior[node.PublicKey]
			connectionsLock_senior.Unlock()
			if !ok {
				flag1 = false
			}
		}
		if flag1 {

			for idx, node := range selectednodes {
				tx := db.DB.Begin()
				if err := tx.Delete(PendingNode2{}, node.Id).Error; err != nil {
					tx.Rollback()
					fmt.Println(err)
				} else {
					tx.Commit()
					connectionsLock_senior.Lock()
					conn := connections_senior[node.PublicKey]
					if conn != nil {
						err := conn.WriteMessage(websocket.TextMessage, bytes)
						if err != nil {
							log.Println("Write error:", err)
						}
					}
					aa := Node2{
						PublicKey: node.PublicKey,
						Ip:        node.Ip,
						Port:      node.Port,
						ShardId:   strconv.Itoa(shardID),
						NodeId:    strconv.Itoa(idx),
						Timestamp: time.Now(),
						Beattime:  time.Now(),
					}
					db.DB.Where("publickey = ?", node.PublicKey).Delete(&Node2{})
					db.DB.Model(aa).Create(&aa)

					delete(connections_senior, node.PublicKey)
					connectionsLock_senior.Unlock()
				}
			}

			//nodes := make([]message.NodeInfo, 0)
			//if config.OldNodeinfos!=nil{
			//	nodes = append(nodes,config.OldNodeinfos...)
			//}
			//nodes = append(nodes, ninfos...)
			//shardid := shardID
			//nodeid := -1
			//for _, node := range nodes {
			//	nodeid++
			//	if params.IPmap_nodeTable[uint64(shardid)] == nil {
			//		params.IPmap_nodeTable[uint64(shardid)] = make(map[uint64]string)
			//	}
			//	params.IPmap_nodeTable[uint64(shardid)][uint64(nodeid)] = node.Ip + ":" + node.Port
			//}
			//params.ShardNum = shardid + 1
			fmt.Println("has generated new ipmap for senior:")
			//for i := 0; i < params.ShardNum; i++ {
			//	for j := 0; j < params.NodesInShard; j++ {
			//		fmt.Println("S" + strconv.Itoa(i) + "N" + strconv.Itoa(j) + ":" + params.IPmap_nodeTable[uint64(i)][uint64(j)])
			//	}
			//}
			//d.Ip_nodeTable = params.IPmap_nodeTable
			//d.ChainConfig.ShardNums = uint64(params.ShardNum)
			db.DB.Model(cc).Where("id = ?", cc.Id).Update(&cc)
		}
	}
}
func (d *Supervisor) OpenShard() {
	for {
		time.Sleep(time.Second * 2)
		var pendingnodes []PendingNode
		if err := db.DB.Find(&pendingnodes).Error; err != nil {
			fmt.Println(err)
			continue
		}
		var filterednodes []PendingNode
		for _, node := range pendingnodes {
			if time.Since(node.Beattime).Seconds() < 10 {
				filterednodes = append(filterednodes, node)
			}
		}
		var cc1 Config
		db.DB.Model(cc1).Where("config = ? ", "nodepershard").Find(&cc1)
		nodepershard, _ := strconv.Atoi(cc1.Value)

		if len(filterednodes) < nodepershard {
			continue
		}
		r := rand.New(rand.NewSource(time.Now().UnixNano()))
		for i := range filterednodes {
			// 生成一个随机索引，范围是从i到切片的末尾
			j := r.Intn(i + 1)
			// 交换当前元素和随机选择的元素
			filterednodes[i], filterednodes[j] = filterednodes[j], filterednodes[i]
		}
		var selectednodes = make([]PendingNode, nodepershard)

		var cc Config
		db.DB.Where("config = ?", "shardid").Find(&cc)
		shardID, _ := strconv.Atoi(cc.Value)
		cc.Value = strconv.Itoa(shardID + 1)

		var ninfos = make([]message.NodeInfo, nodepershard)
		for i := 0; i < nodepershard; i++ {
			selectednodes[i] = filterednodes[i]
			ninfos[i] = message.NodeInfo{
				PublicKey: filterednodes[i].PublicKey,
				Ip:        filterednodes[i].Ip,
				Port:      filterednodes[i].Port,
				ShardID:   strconv.Itoa(shardID),
			}
		}
		//var existnodes []Node
		var oldnodes []message.NodeInfo
		//if err := db.DB.Find(&existnodes).Error; err != nil {
		//	fmt.Println(err)
		//} else {
		//	if len(existnodes) > 0 {
		//		for _, node := range existnodes {
		//			oldnodes = append(oldnodes, message.NodeInfo{
		//				PublicKey: node.PublicKey,
		//				Ip:        node.Ip,
		//				Port:      node.Port,
		//				ShardID:   node.ShardId,
		//			})
		//		}
		//	}
		//}
		oldnodes = append(oldnodes, message.NodeInfo{
			PublicKey: "1",
			Ip:        "1",
			Port:      "1",
			ShardID:   "1",
		})

		var proxys1 []Proxy
		db.DB.Model(Proxy{}).Find(&proxys1)
		var proxys []Proxy
		for _, p := range proxys1 {
			if p.IP == global.DomainName {
				proxys = append(proxys, p)
			}
		}

		r1 := rand.New(rand.NewSource(time.Now().UnixNano()))
		for i := range proxys {
			j := r1.Intn(i + 1)
			proxys[i], proxys[j] = proxys[j], proxys[i]
		}

		config_ := message.DynamicConfig{NewNodeinfos: ninfos, OldNodeinfos: oldnodes, ProxyIp: proxys[0].IP, ProxyPort: proxys[0].Port}

		bytes, err := json.Marshal(config_)
		if err != nil {
			fmt.Println(err)
		}

		flag1 := true
		for _, node := range selectednodes {
			connectionsLock.Lock()
			_, ok := connections[node.PublicKey]
			connectionsLock.Unlock()
			if !ok {
				flag1 = false
			}
		}
		if flag1 {

			for idx, node := range selectednodes {
				tx := db.DB.Begin()
				if err := tx.Delete(PendingNode{}, node.Id).Error; err != nil {
					tx.Rollback()
					fmt.Println(err)
				} else {
					tx.Commit()
					connectionsLock.Lock()
					conn := connections[node.PublicKey]
					if conn != nil {
						err := conn.WriteMessage(websocket.TextMessage, bytes)
						if err != nil {
							log.Println("Write error:", err)
						}
					}
					aa := Node{
						PublicKey: node.PublicKey,
						Ip:        node.Ip,
						Port:      node.Port,
						ShardId:   strconv.Itoa(shardID),
						NodeId:    strconv.Itoa(idx),
						Timestamp: time.Now(),
						Beattime:  time.Now(),
					}
					db.DB.Where("publickey = ?", node.PublicKey).Delete(&Node{})
					db.DB.Model(aa).Create(&aa)

					delete(connections, node.PublicKey)
					connectionsLock.Unlock()
				}
			}

			nodes := make([]message.NodeInfo, 0)
			//if config.OldNodeinfos!=nil{
			//	nodes = append(nodes,config.OldNodeinfos...)
			//}
			nodes = append(nodes, ninfos...)
			shardid := shardID
			nodeid := -1
			for _, node := range nodes {
				nodeid++
				if params.IPmap_nodeTable[uint64(shardid)] == nil {
					params.IPmap_nodeTable[uint64(shardid)] = make(map[uint64]string)
				}
				params.IPmap_nodeTable[uint64(shardid)][uint64(nodeid)] = node.Ip + ":" + node.Port
			}
			params.ShardNum = shardid + 1
			fmt.Println("has generated new ipmap:")
			//for i := 0; i < params.ShardNum; i++ {
			//	for j := 0; j < params.NodesInShard; j++ {
			//		fmt.Println("S" + strconv.Itoa(i) + "N" + strconv.Itoa(j) + ":" + params.IPmap_nodeTable[uint64(i)][uint64(j)])
			//	}
			//}
			d.Ip_nodeTable = params.IPmap_nodeTable
			d.ChainConfig.ShardNums = uint64(params.ShardNum)

			//msg_send := message.MergeMessage(message.CShardChange, bytes)
			//for sid := 0; sid < int(d.ChainConfig.ShardNums)-1; sid++ {
			//	for nid := 0; nid < int(d.ChainConfig.Nodes_perShard); nid++ {
			//		go networks.TcpDial(msg_send, d.Ip_nodeTable[uint64(sid)][uint64(nid)])
			//	}
			//}
			if shardid == 0 {
				//go d.SupervisorTxHandling()
			}
			//fp:="small_tree_shard_"+strconv.Itoa(shardid)
			//db1, _ := rawdb.NewLevelDBDatabase(fp, 0, 1, "accountState", false)
			//d.SmallDb = append(d.SmallDb, &db1)
			//triedb1 := triedb.NewDatabase(db1, &triedb.Config{
			//	//Cache:     0,
			//	Preimages: true,
			//	IsVerkle:  false,
			//})
			//d.SmallTriedb = append(d.SmallTriedb, triedb1)
			//Statedb1 := state.NewDatabase(triedb1, nil)
			//d.SmallStatedb = append(d.SmallStatedb, Statedb1)

			//statusTrie := trie.NewEmpty(triedb1)
			//Root := statusTrie.Hash()
			//con := Config{}
			//if er:= db.DB.Model(con).Where("config = ?","shard_"+strconv.Itoa(shardid)+"_root").Find(&con).Error; er != nil {
			//	con.Value = hex.EncodeToString(Root[:])
			//	con.Config = "shard_"+strconv.Itoa(shardid)+"_root"
			//	db.DB.Model(con).Create(&con)
			//}else {
			//	con.Value = hex.EncodeToString(Root[:])
			//	db.DB.Model(con).Where("id = ?",con.Id).Update(&con)
			//}
			db.DB.Model(cc).Where("id = ?", cc.Id).Update(&cc)
		}
	}
}
func (d *Supervisor) DeleteDead_senior() {
	for {
		time.Sleep(time.Second * 5)
		var pendingnodes []PendingNode2
		if err := db.DB.Find(&pendingnodes).Error; err != nil {
			fmt.Println(err)
			continue
		}
		deleted := make([]PendingNode2, 0)
		for _, node := range pendingnodes {
			if time.Since(node.Beattime).Seconds() > 60 {
				deleted = append(deleted, node)
			}
		}
		for _, node := range deleted {
			tx := db.DB.Begin()
			if err := tx.Delete(PendingNode2{}, node.Id).Error; err != nil {
				tx.Rollback()
				fmt.Println(err)
			} else {
				tx.Commit()
				connectionsLock_senior.Lock()
				conn := connections_senior[node.PublicKey]
				go func() {
					if conn != nil {
						conn.Close()
					}
				}()
				delete(connections_senior, node.PublicKey)
				connectionsLock_senior.Unlock()
			}
		}

	}
}
func (d *Supervisor) DeleteDead() {
	for {
		time.Sleep(time.Second * 5)
		var pendingnodes []PendingNode
		if err := db.DB.Find(&pendingnodes).Error; err != nil {
			fmt.Println(err)
			continue
		}
		deleted := make([]PendingNode, 0)
		for _, node := range pendingnodes {
			if time.Since(node.Beattime).Seconds() > 60 {
				deleted = append(deleted, node)
			}
		}
		for _, node := range deleted {
			tx := db.DB.Begin()
			if err := tx.Delete(PendingNode{}, node.Id).Error; err != nil {
				tx.Rollback()
				fmt.Println(err)
			} else {
				tx.Commit()
				connectionsLock.Lock()
				conn := connections[node.PublicKey]
				go func() {
					if conn != nil {
						conn.Close()
					}
				}()
				delete(connections, node.PublicKey)
				connectionsLock.Unlock()
			}
		}

	}
}

type ChangeRate struct {
	Id        uint64    `json:"id" gorm:"primary_key;column:id;AUTO_INCREMENT"`
	ChangeR   string    `json:"change_r" gorm:"column:change_r;type:varchar(255)"`
	Timestamp time.Time `json:"timestamp" gorm:"column:timestamp;type:datetime"`
}

func (c *ChangeRate) TableName() string {
	return "change_rate"
}

type Stability struct {
	Id        uint64    `json:"id" gorm:"primary_key;column:id;AUTO_INCREMENT"`
	Stability string    `json:"stability" gorm:"column:stability;type:varchar(255)"`
	Alpha     string    `json:"alpha" gorm:"column:alpha;type:varchar(255)"`
	Timestamp time.Time `json:"timestamp" gorm:"column:timestamp;type:datetime"`
}

func (c *Stability) TableName() string {
	return "stability"
}
func (d *Supervisor) Doonce() {
	starttime1str := "2025-06-25 02:12:16"
	endtime1str := "2025-07-02 07:18:45"
	layout := "2006-01-02 15:04:05"
	starttime1, _ := time.Parse(layout, starttime1str)
	endtime1, _ := time.Parse(layout, endtime1str)
	nowtime := starttime1
	mm1 := make(map[string]Stability)
	for {
		thetime := nowtime
		str1 := thetime.Format("2006-01-02 15:04:05")
		thetime = thetime.Add(time.Minute)
		str2 := thetime.Format("2006-01-02 15:04:05")
		thetime = thetime.Add(time.Minute)
		str3 := thetime.Format("2006-01-02 15:04:05")
		var r1 Record
		db.DB.Model(r1).Where("type = ? and timestamp between ? and ?", "node", str1, str2).Order("timestamp asc").First(&r1)
		var r2 Record
		db.DB.Model(r2).Where("type = ? and timestamp between ? and ?", "node", str2, str3).Order("timestamp asc").First(&r2)
		var r1nc []NodeCount
		var r2nc []NodeCount
		json.Unmarshal([]byte(r1.Record), &r1nc)
		json.Unmarshal([]byte(r2.Record), &r2nc)

		mm := make(map[string]bool)
		for _, aa := range r1nc {
			mm[aa.ShardID] = true
		}
		count1 := 0
		for _, aa := range r2nc {
			if _, ok := mm[aa.ShardID]; ok {
				count1++
			}
		}

		crf := 1 - float64(count1)/float64(len(r1nc))
		if crf < 0 || crf > 1 {
			crf = 0
		}

		var cr ChangeRate
		crtime := thetime.Add(-time.Minute)
		cr.Timestamp = crtime
		cr.ChangeR = strconv.FormatFloat(crf, 'f', 2, 64)
		db.DB.Model(cr).Create(&cr)

		for alpha := 0.9; alpha > 0; alpha -= 0.2 {
			sb, ok := mm1[strconv.FormatFloat(alpha, 'f', 2, 64)]
			if !ok {
				sb = Stability{
					Stability: "1",
				}
			}
			var sb2 Stability
			sb2.Alpha = strconv.FormatFloat(alpha, 'f', 2, 64)
			sb2.Timestamp = crtime
			s1, e2 := strconv.ParseFloat(sb.Stability, 64)
			if e2 != nil {
				continue
			}
			sb2.Stability = strconv.FormatFloat(alpha*(1-crf)+(1-alpha)*s1, 'f', 2, 64)
			if sb2.Stability == "NaN" {
				sb2.Stability = "0.50"
			}
			db.DB.Model(sb2).Create(&sb2)
			mm1[strconv.FormatFloat(alpha, 'f', 2, 64)] = sb2
		}

		nowtime = nowtime.Add(time.Minute)
		if nowtime.After(endtime1) {
			break
		}
	}
}
func (d *Supervisor) Record() {
	for {
		time.Sleep(60 * time.Second)
		var cc1 Config
		db.DB.Model(cc1).Where("config = ? ", "nodepershard").Find(&cc1)
		nodepershard, _ := strconv.Atoi(cc1.Value)
		nodepershard = nodepershard * 2 / 3
		var results []NodeCount
		err := db.DB.Raw("SELECT shardid, COUNT(*) as count FROM nodes WHERE TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 GROUP BY shardid having count(*) > " + strconv.Itoa(nodepershard)).Scan(&results).Error
		if err != nil {
			fmt.Println(err)
			continue
		}
		marshal, e := json.Marshal(results)
		if e != nil {
			fmt.Println(e)
			continue
		}
		var r1 Record
		r1.Type = "node"
		r1.Timestamp = time.Now()
		r1.Record = string(marshal)

		var ro Record
		db.DB.Model(ro).Where("type = ?", "node").Order("timestamp desc").First(&ro)

		err = db.DB.Model(r1).Create(&r1).Error
		if err != nil {
			fmt.Println(err)
			continue
		}

		var r2nc []NodeCount
		err = json.Unmarshal([]byte(ro.Record), &r2nc)
		if err != nil {
			fmt.Println(err)
			continue
		}

		mm := make(map[string]bool)
		for _, aa := range r2nc {
			mm[aa.ShardID] = true
		}
		count1 := 0
		for _, aa := range results {
			if _, ok := mm[aa.ShardID]; ok {
				count1++
			}
		}

		var cr ChangeRate
		crf := 1 - float64(count1)/float64(len(r2nc))
		cr.ChangeR = strconv.FormatFloat(crf, 'f', 2, 64)
		cr.Timestamp = time.Now()
		db.DB.Model(cr).Create(&cr)

		for alpha := 0.9; alpha > 0; alpha -= 0.2 {
			var sb Stability
			if e1 := db.DB.Model(sb).Where("alpha = ?", strconv.FormatFloat(alpha, 'f', 2, 64)).Order("timestamp desc").First(&sb).Error; e1 != nil {
				continue
			}
			var sb2 Stability
			sb2.Alpha = strconv.FormatFloat(alpha, 'f', 2, 64)
			sb2.Timestamp = time.Now()
			s1, e2 := strconv.ParseFloat(sb.Stability, 64)
			if e2 != nil {
				continue
			}
			sb2.Stability = strconv.FormatFloat(alpha*(1-crf)+(1-alpha)*s1, 'f', 2, 64)
			db.DB.Model(sb2).Create(&sb2)
		}

		var results2 []IpCount
		err = db.DB.Raw("select ip,count(*) as count from nodes where TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 group by ip").Scan(&results2).Error
		if err != nil {
			fmt.Println(err)
			continue
		}

		for i := 0; i < len(results2); i++ {
			ip := results2[i].Ip
			var Ip1 Ip
			if err1 := db.DB.Model(Ip1).Where("ip = ?", ip).Find(&Ip1).Error; err1 != nil {
				url := "https://apis.map.qq.com/ws/location/v1/ip?key=TA2BZ-UWV6C-RQI2H-AG4O7-2ZOAE-XGFTM&ip=" + ip + "&output=json"
				//url := fmt.Sprintf("https://ipinfo.io/%s", ip)
				resp, err2 := http.Get(url)
				if err2 != nil {
					continue
				}
				defer resp.Body.Close()
				body, err3 := ioutil.ReadAll(resp.Body)
				if err3 != nil {
					continue
				}

				// 解析 JSON 响应
				var ipInfo Response
				err4 := json.Unmarshal(body, &ipInfo)
				if err4 != nil {
					continue
				}
				if ipInfo.Status == 0 {
					ad := ipInfo.Result.AdInfo
					location1 := ipInfo.Result.Location
					results2[i].Loc = ad.Nation + ad.Province + ad.City + ad.District + " 纬度:" + fmt.Sprintf("%f", location1.Lat) + " 经度:" + fmt.Sprintf("%f", location1.Lng)
					Ip1.Ip = ip
					Ip1.Loc = results2[i].Loc
					db.DB.Model(Ip1).Create(&Ip1)
					time.Sleep(500 * time.Millisecond)
				}
			} else {
				results2[i].Loc = Ip1.Loc
			}
		}
		marshal2, e := json.Marshal(results2)
		if e != nil {
			fmt.Println(e)
			continue
		}
		var r2 Record
		r2.Type = "ip"
		r2.Timestamp = time.Now()
		r2.Record = string(marshal2)
		err = db.DB.Model(r2).Create(&r2).Error

		if err != nil {
			fmt.Println(err)
			continue
		}

	}
}

func (d *Supervisor) RecordId() {
	var cc Config
	db.DB.Model(cc).Where("config = ?", "shardid").Find(&cc)
	presid, _ := strconv.Atoi(cc.Value)
	now := time.Now()
	unixTimestamp := now.Unix()
	hour := unixTimestamp / (60 * 60)

	for {
		time.Sleep(1 * time.Second)

		now1 := time.Now()
		unixTimestamp1 := now1.Unix()
		hour1 := unixTimestamp1 / (60 * 60)

		if hour1 != hour {
			var cc1 Config
			db.DB.Model(cc1).Where("config = ?", "shardid").Find(&cc1)
			sid, _ := strconv.Atoi(cc1.Value)
			incr := sid - presid
			presid = sid
			hour = hour1
			var idrec IdRecord
			idrec.Incr = uint64(incr)
			idrec.Time = uint64(hour1)
			db.DB.Model(idrec).Create(&idrec)
		}

	}
}

func (d *Supervisor) RecordId_senior() {
	var cc Config
	db.DB.Model(cc).Where("config = ?", "shardid_senior").Find(&cc)
	presid, _ := strconv.Atoi(cc.Value)
	now := time.Now()
	unixTimestamp := now.Unix()
	hour := unixTimestamp / (60 * 60)

	for {
		time.Sleep(1 * time.Second)

		now1 := time.Now()
		unixTimestamp1 := now1.Unix()
		hour1 := unixTimestamp1 / (60 * 60)

		if hour1 != hour {
			var cc1 Config
			db.DB.Model(cc1).Where("config = ?", "shardid_senior").Find(&cc1)
			sid, _ := strconv.Atoi(cc1.Value)
			incr := sid - presid
			presid = sid
			hour = hour1
			var idrec IdRecord2
			idrec.Incr = uint64(incr)
			idrec.Time = uint64(hour1)
			db.DB.Model(idrec).Create(&idrec)
		}

	}
}

type IdRecord struct {
	Id   uint64 `json:"id" gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Time uint64 `json:"time" gorm:"column:time"`
	Incr uint64 `json:"incr" gorm:"column:incr"`
}
type IdRecord2 struct {
	Id   uint64 `json:"id" gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Time uint64 `json:"time" gorm:"column:time"`
	Incr uint64 `json:"incr" gorm:"column:incr"`
}
type Record struct {
	Id        uint64    `json:"id" gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Record    string    `json:"record" gorm:"column:record"`
	Type      string    `json:"type" gorm:"column:type"`
	Timestamp time.Time `json:"timestamp" gorm:"column:timestamp"`
}

func (*Record) TableName() string {
	return "record"
}
func (*IdRecord) TableName() string {
	return "idrecord"
}
func (*IdRecord2) TableName() string {
	return "idrecord2"
}
