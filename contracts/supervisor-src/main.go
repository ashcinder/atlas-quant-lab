package main

import (
	"blockEmulator/build"
	"blockEmulator/nat"
	"blockEmulator/params"
	"crypto/sha256"
	"fmt"
	"log"
	"net"
	"net/http"
	_ "net/http/pprof"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum/common/mclock"
	"github.com/huin/goupnp/dcps/internetgateway1"
)

var (
	// network config
	shardNum int
	nodeNum  int
	shardID  int
	nodeID   int

	// supervisor or not
	isSupervisor bool

	// batch running config
	isGen                bool
	isGenerateForExeFile bool
)

func check(arr []byte) bool {
	for i := 0; i < len(arr) && i < 4; i++ {
		if arr[i] != 0 {
			return false
		}
	}
	return true
}

func worker(id int, wg *sync.WaitGroup, start, end int, prefix string, preHash [32]byte, difficulty int, resultChan chan<- int, doneChan chan<- bool) {
	defer wg.Done()

	for i := start; i < end; i++ {
		// 合并预计算的哈希和当前数字的哈希
		var hash [32]byte
		sum256 := sha256.Sum256([]byte(strconv.Itoa(i)))
		for j := 0; j < 32; j++ {
			hash[j] = preHash[j] ^ sum256[j]
		}

		if check(hash[:]) {
			resultChan <- i
			//doneChan <- true
			return
		}
	}
}

//func ReqProblem(){
//
//	_req := &message.GetProblemReq{
//		PublicKey: "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUNiVENDQWhLZ0F3SUJBZ0lERFZtek1Bb0dDQ3FHU000OUJBTUNNR1l4Q3pBSkJnTlZCQVlUQW1OdU1SQXcKRGdZRFZRUUlFd2RpWldscWFXNW5NUkF3RGdZRFZRUUhFd2RpWldscWFXNW5NUTB3Q3dZRFZRUUtFd1F4TURBMgpNUkl3RUFZRFZRUUxFd2x5YjI5MExXTmxjblF4RURBT0JnTlZCQU1UQjJOaExqRXdNRFl3SGhjTk1qVXdOVEEzCk1UUXhOREUzV2hjTk16UXdOVEExTVRReE5ERTNXakJzTVFzd0NRWURWUVFHRXdKamJqRVFNQTRHQTFVRUNCTUgKWW1WcGFtbHVaekVRTUE0R0ExVUVCeE1IWW1WcGFtbHVaekVOTUFzR0ExVUVDaE1FTVRBd05qRVBNQTBHQTFVRQpDeE1HWTJ4cFpXNTBNUmt3RndZRFZRUURFeEJ0ZVhWelpYSXVjMmxuYmk0eE1EQTJNRmt3RXdZSEtvWkl6ajBDCkFRWUlLb1pJemowREFRY0RRZ0FFQzRjVTlUYUFtaVJsRFhIOTdkZkJXcklqcG52UDdTR2syb2pGL0RvVXFmRE4KK3huTVVCOEZ3QlBnNEVIMWtXV1llVzJWaC9MNVdJMi9RUmVzL1RBYnJhT0JxRENCcFRBT0JnTlZIUThCQWY4RQpCQU1DQWFZd0R3WURWUjBsQkFnd0JnWUVWUjBsQURBcEJnTlZIUTRFSWdRZ2VxZlpJMzlldUdmUWd5ZU50eHJ0CkxsekRzQk4xalNXU2dLRzZ6RThhOTNZd0t3WURWUjBqQkNRd0lvQWcvYnFxQnJXUTM5ZTRualhrTXVPMnZiaWkKemJkdUYwSlJrYWU5VHNzUHA4Y3dLZ1lEVlIwUkJDTXdJWUlKYkc5allXeG9iM04wZ2c1amFHRnBibTFoYTJWeQpMbTl5WjRjRWZ3QUFBVEFLQmdncWhrak9QUVFEQWdOSkFEQkdBaUVBcThzNGRNUGJzTm4zU3BiSXRrbWVPdGh3CmM1YS95N3VwM2wwKzFpU2pKT0VDSVFDeUFGZ3llWmV5RmkwSFk0OWNINDlYbEREdTZGTjFrR3JKMmFyK0xFUVAKUnc9PQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==",
//	}
//	PrivateKey:= "LS0tLS1CRUdJTiBFQyBQUklWQVRFIEtFWS0tLS0tCk1IY0NBUUVFSU5SVW1VT3U4a1JabXgxUWd6WEVnRmJDSi9TYklNNHQvNkJoaXlFQ0RObjJvQW9HQ0NxR1NNNDkKQXdFSG9VUURRZ0FFQzRjVTlUYUFtaVJsRFhIOTdkZkJXcklqcG52UDdTR2syb2pGL0RvVXFmRE4reG5NVUI4Rgp3QlBnNEVIMWtXV1llVzJWaC9MNVdJMi9RUmVzL1RBYnJRPT0KLS0tLS1FTkQgRUMgUFJJVkFURSBLRVktLS0tLQo="
//	rand:=uuid.New().String()
//	_req.RandomStr = rand
//
//	_req.Sign =  sha256.Sum256([]byte(rand + PrivateKey))
//
//	jsonData, _ := json.Marshal(_req)
//	req, err := http.NewRequest("POST", "http://127.0.0.1:8080/getProblem", bytes.NewBuffer(jsonData))
//	if err != nil {
//		fmt.Println("Error creating request:", err)
//		return
//	}
//
//	// 设置请求头
//	req.Header.Set("Content-Type", "application/json")
//
//	// 发送请求
//	client := &http.Client{}
//	resp, err := client.Do(req)
//	if err != nil {
//		fmt.Println("Error sending request:", err)
//		return
//	}
//	defer resp.Body.Close() // 确保关闭响应体
//
//	// 读取响应体
//	body, err := io.ReadAll(resp.Body)
//	if err != nil {
//		fmt.Println("Error reading response body:", err)
//		return
//	}
//
//	// 输出响应状态码和内容
//	fmt.Println("Response Status:", resp.Status)
//	fmt.Println("Response Body:", string(body))
//
//}

func doPortMapping(natm nat.Interface, addr *net.UDPAddr) *net.UDPAddr {
	const (
		protocol = "udp"
		name     = "ethereum discovery"
	)

	var (
		intport    = addr.Port
		extaddr    = &net.UDPAddr{IP: addr.IP, Port: addr.Port}
		mapTimeout = 10 * time.Minute
	)
	addMapping := func() {
		// Get the external address.
		var err error
		extaddr.IP, err = natm.ExternalIP()
		if err != nil {
			fmt.Println("Couldn't get external IP", "err", err)
			return
		}
		// Create the mapping.
		p, err := natm.AddMapping(protocol, extaddr.Port, intport, name, mapTimeout)
		if err != nil {
			fmt.Println("Couldn't add port mapping", "err", err)
			return
		}
		if p != uint16(extaddr.Port) {
			extaddr.Port = int(p)
			fmt.Println("NAT mapped alternative port")
		} else {
			fmt.Println("NAT mapped port")
		}
		// Update IP/port information of the local node.
		//ln.SetStaticIP(extaddr.IP)
		//ln.SetFallbackUDP(extaddr.Port)
	}

	// Perform mapping once, synchronously.
	fmt.Println("Attempting port mapping")
	addMapping()

	// Refresh the mapping periodically.
	go func() {
		refresh := time.NewTimer(mapTimeout)
		defer refresh.Stop()
		for range refresh.C {
			addMapping()
			refresh.Reset(mapTimeout)
		}
	}()

	return extaddr
}

type portMapping struct {
	protocol string
	name     string
	port     int

	// for use by the portMappingLoop goroutine:
	extPort  int // the mapped port returned by the NAT interface
	nextTime mclock.AbsTime
}

func GetExternalIPAddress() {
	clients, _, _ := internetgateway1.NewWANIPConnection1Clients()
	for _, client := range clients {
		device := &client.GetServiceClient().RootDevice.Device

		fmt.Fprintln(os.Stderr, "  Device:", device.FriendlyName)
		if addr, err := client.GetExternalIPAddress(); err != nil {
			fmt.Fprintf(os.Stderr, "    Failed to get external IP address: %v\n", err)
		} else {
			fmt.Fprintf(os.Stderr, "    External IP address: %v\n", addr)
		}
		srv := client.GetServiceClient().Service
		fmt.Println(device.FriendlyName, " :: ", srv.String())
		scpd, err := srv.RequestSCPD()
		if err != nil {
			fmt.Printf("  Error requesting service SCPD: %v\n", err)
		} else {
			fmt.Println("  Available actions:")
			for _, action := range scpd.Actions {
				fmt.Printf("  * %s\n", action.Name)
				for _, arg := range action.Arguments {
					var varDesc string
					if stateVar := scpd.GetStateVariable(arg.RelatedStateVariable); stateVar != nil {
						varDesc = fmt.Sprintf(" (%s)", stateVar.DataType.Name)
					}
					fmt.Printf("    * [%s] %s%s\n", arg.Direction, arg.Name, varDesc)
				}
			}
		}
		if scpd == nil || scpd.GetAction("AddPortMapping") != nil {
			err := client.AddPortMapping("", 53334, "TCP", 53423, "192.168.3.213", true, "Test port mapping", 1000)
			fmt.Println("AddPortMapping: ", err)
		}
	}

}

func main() {
	log.SetOutput(os.Stdout)
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	go func() {
		http.ListenAndServe("localhost:16060", nil)
	}()

	defer func() {
		if err := recover(); err != nil {
			fmt.Println(err)
		}
	}()
	if false {
		GetExternalIPAddress()
		return
	}

	if false {
		portMapping1 := make([]portMapping, 0)
		listenAddr := "0.0.0.0:30301"
		natdesc := "any"
		_, err := nat.Parse(natdesc)
		if err != nil {
			fmt.Printf("-nat: %v\n", err)
		}

		listener, err := net.Listen("tcp4", listenAddr)
		if err != nil {
			fmt.Printf("-1err: %v\n", err)
		}
		tcp, isTCP := listener.Addr().(*net.TCPAddr)
		if isTCP {
			if !tcp.IP.IsLoopback() {
				portMapping1 = append(portMapping1, portMapping{
					protocol: "TCP",
					name:     "hh",
					port:     tcp.Port,
				})
			}
		}

		addr, err := net.ResolveUDPAddr("udp", listenAddr)
		if err != nil {
			fmt.Printf("-ResolveUDPAddr: %v\n", err)
		}
		conn, err := net.ListenUDP("udp", addr)
		if err != nil {
			fmt.Printf("-ListenUDP: %v\n", err)
		}

		laddr := conn.LocalAddr().(*net.UDPAddr)

		if !laddr.IP.IsLoopback() {
			portMapping1 = append(portMapping1, portMapping{
				protocol: "UDP",
				name:     "hh",
				port:     laddr.Port,
			})
		}

		externalIP, err := nat.Any().ExternalIP()
		if err != nil {
			fmt.Printf("-Any: %v\n", err)
		}
		fmt.Println(externalIP)
		for _, m := range portMapping1 {
			external := m.port
			if m.extPort != 0 {
				external = m.extPort
			}
			p, err := nat.Any().AddMapping(m.protocol, external, m.port, m.name, 10*time.Minute)
			if err != nil {
				fmt.Println("Couldn't add port mapping", err)
				return
			}
			// It was mapped!
			m.extPort = int(p)
			fmt.Println("external:", external)
			fmt.Println("m.extPort ", m.extPort)
			if external != m.extPort {
				fmt.Println("NAT mapped alternative port")
			} else {
				fmt.Println("NAT mapped port")
			}
			fmt.Println("m.protocol:", m.protocol)
		}

		//fmt.Println("Before :Listening on", listenerAddr.String())
		//
		//if natm != nil && !listenerAddr.IP.IsLoopback() {
		//	natAddr := doPortMapping(natm, listenerAddr)
		//	if natAddr != nil {
		//		listenerAddr = natAddr
		//	}
		//}
		//fmt.Println("After :Listening on", listenerAddr.String())
		return
	}

	//ReqProblem()
	//return

	//u:= uuid.New()
	//s := u.String()
	//fmt.Println(s)
	//preHash := sha256.Sum256([]byte(s))
	//
	////difficulty := 4 // 可以调整难度
	//workers := 24    // 工作协程数量
	//maxRange := 1000000000
	//found := false
	//
	//
	//	var wg sync.WaitGroup
	//	resultChan := make(chan int, 1)
	//	doneChan := make(chan bool, 1)
	//
	//	perWorker := maxRange / workers
	//
	//	wg.Add(workers)
	//	for i := 0; i < workers; i++ {
	//		start := i*perWorker
	//		end := (i+1)*perWorker
	//		if i == workers-1 {
	//			end =  maxRange // 最后一个处理剩余部分
	//		}
	//		go worker(i, &wg, start, end, s, preHash, 4, resultChan, doneChan)
	//	}
	//
	//	// 启动一个goroutine在找到结果时关闭channel
	//	go func() {
	//		wg.Wait()
	//		doneChan <- true
	//	}()
	//
	//	// 等待结果或完成通知
	//	select {
	//	case i := <-resultChan:
	//		ss := s + strconv.Itoa(i)
	//		sum256 := sha256.Sum256([]byte(ss))
	//
	//		fmt.Println("Found solution:", i)
	//		fmt.Println("Hash:", hex.EncodeToString(sum256[:]))
	//		fmt.Println("String:", ss)
	//		found = true
	//		break
	//	case <-doneChan:
	//		// 当前范围搜索完成，没有找到解
	//		fmt.Printf("No solution found in range %d\n", maxRange)
	//		// 可以在这里调整难度或扩展搜索范围
	//		// difficulty-- // 例如，降低难度
	//		// maxRange *= 2 // 或者扩展搜索范围
	//	}
	//
	//if !found {
	//	fmt.Println("No solution found after searching the entire range")
	//}
	//
	//
	////for i := 0; i < 1000000000; i++ {
	////	ss := s + strconv.Itoa(i)
	////	sum256 := sha256.Sum256([]byte(ss))
	////	if check(sum256[:]) {
	////		fmt.Println(i)
	////		fmt.Println(sum256)
	////	}
	////}
	//
	//return
	// Read basic configs
	params.ReadConfigFile()

	// Generate bat files
	//pflag.BoolVarP(&isGen, "gen", "g", false, "isGen is a bool value, which indicates whether to generate a batch file")
	//pflag.BoolVarP(&isGenerateForExeFile, "shellForExe", "f", false, "isGenerateForExeFile is a bool value, which is effective only if 'isGen' is true; True to generate for an executable, False for 'go run'. ")
	//
	//// Start a node.
	//pflag.IntVarP(&shardNum, "shardNum", "S", params.ShardNum, "shardNum is an Integer, which indicates that how many shards are deployed. ")
	//pflag.IntVarP(&nodeNum, "nodeNum", "N", params.NodesInShard, "nodeNum is an Integer, which indicates how many nodes of each shard are deployed. ")
	//pflag.IntVarP(&shardID, "shardID", "s", -1, "shardID is an Integer, which indicates the ID of the shard to which this node belongs. Value range: [0, shardNum). ")
	//pflag.IntVarP(&nodeID, "nodeID", "n", -1, "nodeID is an Integer, which indicates the ID of this node. Value range: [0, nodeNum).")
	//pflag.BoolVarP(&isSupervisor, "supervisor", "c", false, "isSupervisor is a bool value, which indicates whether this node is a supervisor.")
	//
	//pflag.Parse()
	//
	//params.ShardNum = shardNum
	//params.NodesInShard = nodeNum

	//if isGen {
	//	if isGenerateForExeFile {
	//		// Generate the corresponding .bat file or .sh file based on the detected operating system.
	//		if err := build.GenerateExeBatchByIpTable(nodeNum, shardNum); err != nil {
	//			fmt.Println(err.Error())
	//		}
	//	} else {
	//		// Generate a .bat file or .sh file for running `go run`.
	//		if err := build.GenerateBatchByIpTable(nodeNum, shardNum); err != nil {
	//			fmt.Println(err.Error())
	//		}
	//	}
	//	return
	//}
	//s := "3.141592653589793238462643383279502884197169399375102233"
	//
	//bf := new(big.Float)
	//bf.SetPrec(512)
	//_, success := bf.SetString(s)
	//if !success {
	//	fmt.Println("解析字符串失败")
	//	return
	//}
	//
	//fmt.Println("构造的big.Float:", bf)
	//
	//
	//fmt.Printf("字符串: %s\n", bf.Text('f', -1))
	//
	//fmt.Println()
	//return
	//if isSupervisor {
	nodeNum = 4
	shardNum = 0
	build.BuildSupervisor(uint64(nodeNum), uint64(shardNum))
	//} else {
	//	if shardID >= shardNum || shardID < 0 {
	//		log.Panicf("Wrong ShardID. This ShardID is %d, but only %d shards in the current config. ", shardID, shardNum)
	//	}
	//	if nodeID >= nodeNum || nodeID < 0 {
	//		log.Panicf("Wrong NodeID. This NodeID is %d, but only %d nodes in the current config. ", nodeID, nodeNum)
	//	}
	//	build.BuildNewPbftNode(uint64(nodeID), uint64(nodeNum), uint64(shardID), uint64(shardNum))
	//}
}
