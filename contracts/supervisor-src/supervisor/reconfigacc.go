package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/message"
	"blockEmulator/supervisor/committee"
	"encoding/json"
	"fmt"
	"math/rand"
	"net"
	"strconv"
	"sync"
	"time"
)

func (d *Supervisor) Reconfig() {
	for {
		fmt.Println("start to reconfig")
		d.reconfig()
		var cc Config
		db.DB.Model(cc).Where("config = ?","clpainterval").Find(&cc)
		interval, _ := strconv.Atoi(cc.Value)
		time.Sleep(time.Duration(interval) * time.Second)
		//time.Sleep(86400 * time.Second)
	}
}
func (d *Supervisor) reconfig() {
	d.Lock.Lock()
	defer d.Lock.Unlock()

	var config Config
	db.DB.Model(&Config{}).Where("config = ?", "shardid").Find(&config)
	shardNum, _ := strconv.Atoi(config.Value)
	if shardNum <= 1 {
		return
	}

	partition, _ := d.comMod.(*committee.CLPACommitteeModule).ClpaGraph.CLPA_Partition()
	fmt.Println("new partition map")
	for key, val := range partition {
		d.comMod.(*committee.CLPACommitteeModule).ModifiedMap[key] = val
		//fmt.Println("k:"+key+",value:"+strconv.Itoa(int(val)))
	}




	//var infos []AccInfo
	for k, v := range partition {
		var loc Location
		db.DB.Model(&Location{}).Where("addr = ? ", k).Find(&loc)
		if loc.Location != v {
			fmt.Println("update location of "+loc.Addr+",prev="+strconv.Itoa(int(loc.Location))+",now:"+strconv.Itoa(int(v)))
			loc.Location = v
			db.DB.Model(&Location{}).Where("id = ?", loc.Id).Update(&loc)
		}
		var acc Account
		db.DB.Model(&Account{}).Where("addr = ?", k).Find(&acc)
		//infos = append(infos, AccInfo{
		//	Addr:    k,
		//	ShardId: v,
		//	Balance: acc.Value,
		//})
	}
	//fmt.Println("infos:")
	//fmt.Println(infos)


	d.comMod.(*committee.CLPACommitteeModule).ClpaReset()



	var accs []Account
	db.DB.Model(&Account{}).Find(&accs)


	rand.Seed(time.Now().Unix())
	var infos []AccInfo
	for _, acc := range accs {
		var loc Location
		db.DB.Model(&Location{}).Where("addr = ? ", acc.Addr).Find(&loc)
		//newshardid := rand.Intn(shardNum)
		//if newshardid != shardNum {
		//	loc.Location = uint64(newshardid)
		//	db.DB.Model(&Location{}).Where("id = ?", loc.Id).Update(&loc)
		//}

		//var hash Config
		//db.DB.Model(hash).Where("config = ?", "shard_"+strconv.Itoa(int(newshardid))+"_root").Find(&hash)
		//root, _ := hex.DecodeString(hash.Value)
		//statedb, _ := state.New(common.Hash(root), d.SmallStatedb[newshardid])
		//
		//bytes, _ := hex.DecodeString(acc.Addr)
		//bigint := new(big.Int)
		//bigint.SetString(acc.Value, 10)
		//fromBig, _ := uint256.FromBig(bigint)
		//if fromBig != nil {
		//	statedb.SetBalance(common.Address(bytes), fromBig, tracing.BalanceAddByXBZ)
		//}
		//hash2, _ := statedb.Commit(0, false)
		//root2 := hex.EncodeToString(hash2[:])
		//hash.Value = root2
		//db.DB.Model(hash).Where("id = ? ", hash.Id).Update(hash)
		//d.SmallTriedb[newshardid].Commit(hash2, false)
		//var his RootHistory
		//his.ShardId = uint64(newshardid)
		//his.Root = root2
		//his.Timestamp = time.Now()
		//db.DB.Model(his).Create(&his)

		infos = append(infos, AccInfo{
			Addr:    acc.Addr,
			ShardId: uint64(loc.Location),
			Balance: acc.Value,
		})
	}
	m := M{Infos: infos}
	itByte, _ := json.Marshal(m)
	send_msg := message.MergeMessage(message.CReconfig, itByte)
	ConnectionMapLock.RLock()
	var conns []net.Conn
	var locks []*sync.Mutex
	for i := 0; i < shardNum; i++ {
		for j := 0; j < 8; j++ {
			key := strconv.Itoa(i) + ":" + strconv.Itoa(j)
			conn, ok := ConnectionMap[key]
			if !ok {
				continue
			}
			if err1 := conn.(*net.TCPConn).SetKeepAlive(true); err1 != nil {
				continue
			}
			conns = append(conns, conn)
			mutex, _ := ConnectionLockMap[key]
			locks = append(locks, mutex)
		}
	}
	ConnectionMapLock.RUnlock()
	var wg sync.WaitGroup
	for idx1, conn := range conns {
		wg.Add(1)
		idx2 := idx1
		conn1 := conn
		go func() {
			locks[idx2].Lock()
			defer func() {
				locks[idx2].Unlock()
				wg.Done()
			}()
			conn1.Write(append(send_msg, '\n'))
		}()
	}
	wg.Wait()
}

type M struct {
	Infos []AccInfo
}

type AccInfo struct {
	Addr    string
	ShardId uint64
	Balance string
}
