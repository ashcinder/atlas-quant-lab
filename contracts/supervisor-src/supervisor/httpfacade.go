package supervisor

import (
	"blockEmulator/db"
	"blockEmulator/global"
	crand "crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"math"
	"math/big"
	"net/http"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

type NodeCount struct {
	ShardID string `json:"shardid" gorm:"column:shardid"`
	Count   int    `json:"count" gorm:"column:count"`
}

type IpCount struct {
	Ip    string `json:"ip" gorm:"column:ip"`
	Count int    `json:"count" gorm:"column:count"`
	Loc   string `json:"loc"`
}
type IpInfo struct {
	Ip       string `json:"ip"`
	City     string `json:"city"`
	Region   string `json:"region"`
	Country  string `json:"country"`
	Loc      string `json:"loc"`
	Org      string `json:"org"`
	Postal   string `json:"postal"`
	Timezone string `json:"timezone"`
	Readme   string `json:"readme"`
}

type Location1 struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

type AdInfo struct {
	AdCode     int    `json:"adcode"`
	City       string `json:"city"`
	District   string `json:"district"`
	Nation     string `json:"nation"`
	NationCode int    `json:"nation_code"`
	Province   string `json:"province"`
}

type Result struct {
	AdInfo   AdInfo    `json:"ad_info"`
	IP       string    `json:"ip"`
	Location Location1 `json:"location"`
}

type Response struct {
	Message   string `json:"message"`
	RequestID string `json:"request_id"`
	Result    Result `json:"result"`
	Status    int    `json:"status"`
}
type Result2 struct {
	TotalValue string `json:"total_value"`
}
type Result3 struct {
	TotalValue string `json:"total_value"`
	Time       string `json:"time"`
	Shards     string `json:"shards"`
	Nodes      string `json:"nodes"`
}
type Result4 struct {
	Value string `json:"value"`
	Time  string `json:"time"`
}
type Ip struct {
	Id  uint64 `gorm:"column:id;AUTO_INCREMENT;PRIMARY_KEY"`
	Ip  string `gorm:"column:ip" `
	Loc string `gorm:"column:loc" `
}

func (*Ip) TableName() string {
	return "ip"
}

var starttime = time.Now()

type IdRes struct {
	Time string `json:"time"`
	Incr string `json:"incr"`
}

type DistributeReq struct {
	Targets struct {
		Type        string    `json:"type"`
		ActiveSince time.Time `json:"active_since"`
	} `json:"targets"`
	Amount string `json:"amount"`
	// Ratio  float64 `json:"ratio"`
	Strategy string `json:"strategy"` //进行派发的方式
	TableID  string `json:"table_id"`
}

type IncentivePreviewItem struct {
	Addr   string `json:"addr"`
	Amount string `json:"amount"`
}

type incentivePreviewEntry struct {
	Table     IncentiveTable
	CreatedAt time.Time
}

const incentivePreviewTTL = 10 * time.Minute

var incentivePreviewStore = struct {
	sync.Mutex
	Items map[string]incentivePreviewEntry
}{
	Items: make(map[string]incentivePreviewEntry),
}

func newIncentivePreviewID() string {
	b := make([]byte, 16)
	if _, err := crand.Read(b); err != nil {
		return fmt.Sprintf("fallback-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}

func cloneIncentiveTable(src IncentiveTable) IncentiveTable {
	dst := IncentiveTable{
		Pool:        src.Pool,
		TotalNumber: src.TotalNumber,
		Mapping:     make(map[string]*big.Int, len(src.Mapping)),
	}
	if src.TotalAmount != nil {
		dst.TotalAmount = new(big.Int).Set(src.TotalAmount)
	}
	for addr, amount := range src.Mapping {
		if amount == nil {
			dst.Mapping[addr] = nil
			continue
		}
		dst.Mapping[addr] = new(big.Int).Set(amount)
	}
	return dst
}

func getIncentivePreview(tableID string) (IncentiveTable, bool) {
	if tableID == "" {
		return IncentiveTable{}, false
	}

	incentivePreviewStore.Lock()
	defer incentivePreviewStore.Unlock()

	now := time.Now()
	for id, entry := range incentivePreviewStore.Items {
		if now.Sub(entry.CreatedAt) > incentivePreviewTTL {
			delete(incentivePreviewStore.Items, id)
		}
	}

	entry, ok := incentivePreviewStore.Items[tableID]
	if !ok {
		return IncentiveTable{}, false
	}
	return cloneIncentiveTable(entry.Table), true
}

func deleteIncentivePreview(tableID string) {
	incentivePreviewStore.Lock()
	delete(incentivePreviewStore.Items, tableID)
	incentivePreviewStore.Unlock()
}

func parseDistributeStrategy(name string) (DistributeStrategy, error) {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "even":
		return Even, nil
	case "random":
		return Random, nil
	case "stake":
		return Stake, nil
	default:
		return nil, fmt.Errorf("invalid strategy")
	}
}

func (d *Supervisor) RunHTTP() {

	r := gin.Default()
	if err := r.SetTrustedProxies([]string{"127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}); err != nil {
		log.Fatal(err)
	}
	r.Use(CorsConfig())
	r.Use(func(c *gin.Context) {
		// 将 Supervisor 实例存储在上下文中
		c.Set("supervisor", d)
		c.Next()
	})

	r.LoadHTMLGlob("html/*")
	r.Static("/static", "./static")

	r.GET("/1dsd1e2fgowewWjb4KDq1Pdl5ekPe28udn10q23cdap1ngs", func(c *gin.Context) {
		c.HTML(http.StatusOK, "index.html", nil)
	})
	r.GET("/", func(c *gin.Context) {
		c.HTML(http.StatusOK, "index2.html", nil)
	})

	router := r.Group("/")

	router.POST("fkhbqjv72hduUw6Hq0Of", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		floorValue := math.Floor(tf)
		intValue := int64(floorValue)

		var idrec []IdRecord

		now := time.Now()
		unixTimestamp := now.Unix()
		hour := unixTimestamp / (60 * 60)

		db.DB.Model(IdRecord{}).Where("time between ? and ?", hour-intValue+1, hour).Order("time ASC").Find(&idrec)
		var idres = make([]IdRes, 0)
		for _, aa := range idrec {

			seconds := aa.Time * 60 * 60

			// 创建一个新的 time.Time 对象，从 Unix 纪元开始加上这些秒数
			calculatedTime := time.Unix(int64(seconds), 0)

			// 格式化为字符串
			formattedTime := calculatedTime.Format("2006-01-02 15:04:05")
			idres = append(idres, IdRes{
				Time: formattedTime,
				Incr: strconv.Itoa(int(aa.Incr)),
			})
		}
		c.JSON(http.StatusOK, gin.H{"msg": idres})

	})

	router.POST("fygd82hqYA0r3hivwtntr3ntr3", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}

		tf *= 60
		floored := int(math.Floor(tf))
		now := time.Now()
		end := now.Add(-time.Minute * time.Duration(floored))
		str1 := now.Format("2006-01-02 15:04:05")
		str2 := end.Format("2006-01-02 15:04:05")
		res := make([]Result4, 0)
		var rec []ChangeRate

		db.DB.Model(ChangeRate{}).Where("timestamp between ? and ?", str2, str1).Order("timestamp asc").Find(&rec)
		for _, re := range rec {
			res = append(res, Result4{
				Value: re.ChangeR,
				Time:  re.Timestamp.Format("2006-01-02 15:04:05"),
			})
		}
		c.JSON(http.StatusOK, gin.H{"msg": res})
	})

	////junior
	//router.POST("fygd82hqYA0r3hivwtntr3ntr311",func(c *gin.Context) {
	//	t := c.Query("time")
	//	tf, err := strconv.ParseFloat(t, 64)
	//	if err != nil {
	//		c.JSON(200, gin.H{})
	//		return
	//	}
	//
	//	tf *= 60
	//	floored := int(math.Floor(tf))
	//	now := time.Now()
	//	end := now.Add(- time.Minute * time.Duration(floored))
	//	str1 := now.Format("2006-01-02 15:04:05")
	//	str2 := end.Format("2006-01-02 15:04:05")
	//	res := make([]Result4,0)
	//	var rec []ChangeRate
	//
	//	db.DB.Model(ChangeRate{}).Where("timestamp between ? and ? and (type = ? or type is null)", str2, str1,"junior").Order("timestamp asc").Find(&rec)
	//	for _, re := range rec {
	//		res = append(res, Result4{
	//			Value: re.ChangeR,
	//			Time:  re.Timestamp.Format("2006-01-02 15:04:05"),
	//		})
	//	}
	//	c.JSON(http.StatusOK, gin.H{"msg":res})
	//})
	router.POST("fygd82hqYA0r3hivwtntr3ntr4", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}

		tf *= 60
		floored := int(math.Floor(tf))
		now := time.Now()
		end := now.Add(-time.Minute * time.Duration(floored))
		str1 := now.Format("2006-01-02 15:04:05")
		str2 := end.Format("2006-01-02 15:04:05")
		res := make([]Result4, 0)
		var rec []Stability

		db.DB.Model(Stability{}).Where("alpha = ? and timestamp between ? and ?", strconv.FormatFloat(0.90, 'f', 2, 64), str2, str1).Order("timestamp asc").Find(&rec)
		for _, re := range rec {
			res = append(res, Result4{
				Value: re.Stability,
				Time:  re.Timestamp.Format("2006-01-02 15:04:05"),
			})
		}
		c.JSON(http.StatusOK, gin.H{"msg": res})
	})
	router.POST("aaa123456", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		floored := int(math.Floor(tf))

		if floored <= 0 || floored > 24 {
			c.JSON(200, gin.H{})
			return
		}

		t2 := time.Now()
		roundedHour := t2.Truncate(time.Hour)
		count := floored
		thetime := roundedHour
		var res []Result3
		for {
			if count == 0 {
				break
			}
			str1 := thetime.Format("2006-01-02 15:04:05")
			thetime = thetime.Add(-time.Hour)
			str2 := thetime.Format("2006-01-02 15:04:05")
			var result Result2
			err = db.DB.Raw("SELECT SUM(CAST(tx2.value AS UNSIGNED)) AS total_value FROM tx2 WHERE tx2.timestamp between ? and ? ", str2, str1).Scan(&result).Error
			if err != nil {
				fmt.Println(err)
				c.JSON(http.StatusOK, gin.H{})
				return
			}

			bi := new(big.Float)
			bi.SetString(result.TotalValue)
			unit := new(big.Float)
			unit.SetString(global.Uint)
			bi.Quo(bi, unit)

			res = append(res, Result3{
				TotalValue: bi.Text('f', -1),
				Time:       str2,
				Shards:     "123",
				Nodes:      "123",
			})
			count--
		}
		c.JSON(http.StatusOK, gin.H{"msg": res})
	})
	router.POST("fygd82hqYA0r3hivwtntr3ntr2", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		floored := int(math.Floor(tf))

		t2 := time.Now()
		roundedHour := t2.Truncate(time.Hour)
		count := floored
		thetime := roundedHour
		var res []Result3
		for {
			if count == 0 {
				break
			}

			str1 := thetime.Format("2006-01-02 15:04:05")
			thetime = thetime.Add(-time.Hour)
			str2 := thetime.Format("2006-01-02 15:04:05")
			var result Result2
			err = db.DB.Raw("SELECT SUM(CAST(tx2.value AS UNSIGNED)) AS total_value FROM tx2 WHERE tx2.timestamp between ? and ? ", str2, str1).Scan(&result).Error
			if err != nil {
				fmt.Println(err)
				c.JSON(http.StatusOK, gin.H{})
				return
			}

			var r1 []Record
			err = db.DB.Model(Record{}).Where("timestamp between ? and ? ", str2, str1).Find(&r1).Error
			if err != nil {
				fmt.Println(err)
				c.JSON(http.StatusOK, gin.H{})
				return
			}
			nodecount := 0
			shardcount := len(r1)
			for _, record := range r1 {
				var nn []NodeCount
				json.Unmarshal([]byte(record.Record), &nn)
				for _, nnn := range nn {
					nodecount += nnn.Count
					shardcount++
				}
			}
			shardcount /= len(r1)
			nodecount /= len(r1)

			bi := new(big.Float)
			bi.SetString(result.TotalValue)
			unit := new(big.Float)
			unit.SetString(global.Uint)
			bi.Quo(bi, unit)

			res = append(res, Result3{
				TotalValue: bi.Text('f', -1),
				Time:       str2,
				Shards:     strconv.Itoa(shardcount),
				Nodes:      strconv.Itoa(nodecount),
			})
			count--
		}
		c.JSON(http.StatusOK, gin.H{"msg": res})
	})
	router.POST("aaaa11111", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		if tf <= 0 || tf > 24 {
			c.JSON(200, gin.H{"msg": "查询小时数超过限制，最大24"})
			return
		}
		tf = tf * 3600
		truncated := math.Trunc(tf)

		end := time.Now()
		str2 := end.Format("2006-01-02 15:04:05")
		front := end.Add(-time.Duration(truncated) * time.Second)
		str1 := front.Format("2006-01-02 15:04:05")

		//str := strconv.FormatFloat(truncated, 'f', 0, 64)

		//var totalValueStr string
		var result Result2
		//err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE TIMESTAMPDIFF(SECOND, timestamp, NOW()) BETWEEN 0 AND "+str).Scan(&result).Error
		err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE timestamp BETWEEN ? AND ?", str1, str2).Scan(&result).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, gin.H{})
			return
		}
		totalValueStr := result.TotalValue
		bi := new(big.Float)
		bi.SetString(totalValueStr)
		unit := new(big.Float)
		unit.SetString(global.Uint)
		bi.Quo(bi, unit)
		c.JSON(http.StatusOK, gin.H{"msg": bi.Text('f', -1)})

	})

	//junior
	router.POST("fygd82hqYA0r3hivwtntr3ntr111", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		tf = tf * 3600
		truncated := math.Trunc(tf)
		//str := strconv.FormatFloat(truncated, 'f', 0, 64)

		end := time.Now()
		str2 := end.Format("2006-01-02 15:04:05")
		front := end.Add(-time.Duration(truncated) * time.Second)
		str1 := front.Format("2006-01-02 15:04:05")

		//var totalValueStr string
		var result Result2
		//err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE TIMESTAMPDIFF(SECOND, timestamp, NOW()) BETWEEN 0 AND "+str).Scan(&result).Error
		err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE timestamp BETWEEN ? AND ? and (type = ? or type is null)", str1, str2, "junior").Scan(&result).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, gin.H{})
			return
		}
		totalValueStr := result.TotalValue
		bi := new(big.Float)
		bi.SetString(totalValueStr)
		unit := new(big.Float)
		unit.SetString(global.Uint)
		bi.Quo(bi, unit)
		c.JSON(http.StatusOK, gin.H{"msg": bi.Text('f', -1)})

	})
	//senior
	router.POST("fygd82hqYA0r3hivwtntr3ntr222", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		tf = tf * 3600
		truncated := math.Trunc(tf)
		//str := strconv.FormatFloat(truncated, 'f', 0, 64)

		end := time.Now()
		str2 := end.Format("2006-01-02 15:04:05")
		front := end.Add(-time.Duration(truncated) * time.Second)
		str1 := front.Format("2006-01-02 15:04:05")

		//var totalValueStr string
		var result Result2
		//err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE TIMESTAMPDIFF(SECOND, timestamp, NOW()) BETWEEN 0 AND "+str).Scan(&result).Error
		err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE timestamp BETWEEN ? AND ? and type = ?", str1, str2, "senior").Scan(&result).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, gin.H{})
			return
		}
		totalValueStr := result.TotalValue
		bi := new(big.Float)
		bi.SetString(totalValueStr)
		unit := new(big.Float)
		unit.SetString(global.Uint)
		bi.Quo(bi, unit)
		c.JSON(http.StatusOK, gin.H{"msg": bi.Text('f', -1)})

	})
	router.POST("fygd82hqYA0r3hivwtntr3ntr", func(c *gin.Context) {
		t := c.Query("time")
		tf, err := strconv.ParseFloat(t, 64)
		if err != nil {
			c.JSON(200, gin.H{})
			return
		}
		tf = tf * 3600
		truncated := math.Trunc(tf)
		//str := strconv.FormatFloat(truncated, 'f', 0, 64)

		end := time.Now()
		str2 := end.Format("2006-01-02 15:04:05")
		front := end.Add(-time.Duration(truncated) * time.Second)
		str1 := front.Format("2006-01-02 15:04:05")

		//var totalValueStr string
		var result Result2
		//err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE TIMESTAMPDIFF(SECOND, timestamp, NOW()) BETWEEN 0 AND "+str).Scan(&result).Error
		err = db.DB.Raw("SELECT SUM(CAST(value AS UNSIGNED)) AS total_value FROM tx2 WHERE timestamp BETWEEN ? AND ?", str1, str2).Scan(&result).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, gin.H{})
			return
		}
		totalValueStr := result.TotalValue
		bi := new(big.Float)
		bi.SetString(totalValueStr)
		unit := new(big.Float)
		unit.SetString(global.Uint)
		bi.Quo(bi, unit)
		c.JSON(http.StatusOK, gin.H{"msg": bi.Text('f', -1)})

	})
	//router.POST("lsdagfhugy7beYHd",func(c *gin.Context) {
	//	since := time.Since(starttime)
	//	seconds := int(since.Seconds())
	//	days := seconds / (24 * 3600)
	//	hours := (seconds % (24 * 3600)) / 3600
	//	minutes := (seconds % 3600) / 60
	//	seconds = seconds % 60
	//	res:=""
	//	if days > 0 {
	//		res =  fmt.Sprintf("%d天%d小时%d分%d秒", days, hours, minutes, seconds)
	//	} else if hours > 0 {
	//		res =  fmt.Sprintf("%d小时%d分%d秒", hours, minutes, seconds)
	//	} else if minutes > 0 {
	//		res =  fmt.Sprintf("%d分%d秒", minutes, seconds)
	//	} else {
	//		res =  fmt.Sprintf("%d秒", seconds)
	//	}
	//	c.JSON(http.StatusOK, gin.H{"msg":res})
	//})

	router.POST("liveshard87yf12fh1bsUQ", func(c *gin.Context) {
		var results []NodeCount
		var cc1 Config
		db.DB.Model(cc1).Where("config = ? ", "nodepershard").Find(&cc1)
		nodepershard, _ := strconv.Atoi(cc1.Value)
		nodepershard = nodepershard * 2 / 3
		err := db.DB.Raw("SELECT shardid, COUNT(*) as count FROM nodes WHERE TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 GROUP BY shardid having count(*) > " + strconv.Itoa(nodepershard)).Scan(&results).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, results)
			return
		}
		c.JSON(http.StatusOK, results)
	})

	router.POST("liveshard87yf12fh1bsUQ333", func(c *gin.Context) {
		var results []NodeCount
		var cc1 Config
		db.DB.Model(cc1).Where("config = ? ", "nodepershard_senior").Find(&cc1)
		nodepershard, _ := strconv.Atoi(cc1.Value)
		nodepershard = nodepershard * 2 / 3
		err := db.DB.Raw("SELECT shardid, COUNT(*) as count FROM nodes2 WHERE TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 GROUP BY shardid having count(*) > " + strconv.Itoa(nodepershard)).Scan(&results).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, results)
			return
		}
		c.JSON(http.StatusOK, results)
	})
	router.POST("ipgfdsg128cYwdyu1fv8Qp1222", func(c *gin.Context) {
		var results []IpCount
		err := db.DB.Raw("select ip,count(*) as count from nodes2 where TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 group by ip").Scan(&results).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, results)
			return
		}

		for i := 0; i < len(results); i++ {
			ip := results[i].Ip
			var Ip1 Ip
			if err1 := db.DB.Model(Ip1).Where("ip = ?", ip).Find(&Ip1).Error; err1 != nil {
				url := "https://apis.map.qq.com/ws/location/v1/ip?key=TA2BZ-UWV6C-RQI2H-AG4O7-2ZOAE-XGFTM&ip=" + ip + "&output=json"
				//url := fmt.Sprintf("https://ipinfo.io/%s", ip)
				resp, err1 := http.Get(url)
				if err1 != nil {
					continue
				}
				defer resp.Body.Close()
				body, err2 := ioutil.ReadAll(resp.Body)
				if err2 != nil {
					continue
				}

				// 解析 JSON 响应
				var ipInfo Response
				err2 = json.Unmarshal(body, &ipInfo)
				if err2 != nil {
					continue
				}
				if ipInfo.Status == 0 {
					ad := ipInfo.Result.AdInfo
					location1 := ipInfo.Result.Location
					results[i].Loc = ad.Nation + ad.Province + ad.City + ad.District + " 纬度:" + fmt.Sprintf("%f", location1.Lat) + " 经度:" + fmt.Sprintf("%f", location1.Lng)
					Ip1.Ip = ip
					Ip1.Loc = results[i].Loc
					db.DB.Model(Ip1).Create(&Ip1)
					time.Sleep(500 * time.Millisecond)
				}
			} else {
				results[i].Loc = Ip1.Loc
			}

			//results[i].Loc =ipInfo.Country+ " " + ipInfo.Region+" "+ipInfo.City
		}
		c.JSON(http.StatusOK, results)

	})

	router.POST("ipgfdsg128cYwdyu1fv8Qp1", func(c *gin.Context) {
		var results []IpCount
		err := db.DB.Raw("select ip,count(*) as count from nodes where TIMESTAMPDIFF(SECOND, beattime, NOW()) BETWEEN 0 AND 60 group by ip").Scan(&results).Error
		if err != nil {
			fmt.Println(err)
			c.JSON(http.StatusOK, results)
			return
		}

		for i := 0; i < len(results); i++ {
			ip := results[i].Ip
			var Ip1 Ip
			if err1 := db.DB.Model(Ip1).Where("ip = ?", ip).Find(&Ip1).Error; err1 != nil {
				url := "https://apis.map.qq.com/ws/location/v1/ip?key=TA2BZ-UWV6C-RQI2H-AG4O7-2ZOAE-XGFTM&ip=" + ip + "&output=json"
				//url := fmt.Sprintf("https://ipinfo.io/%s", ip)
				resp, err1 := http.Get(url)
				if err1 != nil {
					continue
				}
				defer resp.Body.Close()
				body, err2 := ioutil.ReadAll(resp.Body)
				if err2 != nil {
					continue
				}

				// 解析 JSON 响应
				var ipInfo Response
				err2 = json.Unmarshal(body, &ipInfo)
				if err2 != nil {
					continue
				}
				if ipInfo.Status == 0 {
					ad := ipInfo.Result.AdInfo
					location1 := ipInfo.Result.Location
					results[i].Loc = ad.Nation + ad.Province + ad.City + ad.District + " 纬度:" + fmt.Sprintf("%f", location1.Lat) + " 经度:" + fmt.Sprintf("%f", location1.Lng)
					Ip1.Ip = ip
					Ip1.Loc = results[i].Loc
					db.DB.Model(Ip1).Create(&Ip1)
					time.Sleep(500 * time.Millisecond)
				}
			} else {
				results[i].Loc = Ip1.Loc
			}

			//results[i].Loc =ipInfo.Country+ " " + ipInfo.Region+" "+ipInfo.City
		}
		c.JSON(http.StatusOK, results)

	})

	router.GET("countcontract", func(c *gin.Context) {
		var count int64

		// Execute the query
		err := db.DB.Model(&db.ContractInvoke{}).Select("COUNT(DISTINCT `to`)").Row().Scan(&count)
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"n1": err.Error()})
			return
		}

		c.JSON(http.StatusOK, gin.H{"m": count})
	})

	router.POST("hugisfdauyhu2DhdsUf28bvfh26tvY2vhqpo01bYQP", func(c *gin.Context) {
		cmd := exec.Command("systemctl", "restart", "super")
		output, err := cmd.CombinedOutput()
		if err != nil {
			fmt.Printf("Failed to execute command: %v\n", err)
			fmt.Printf("Output: %s\n", output)
			c.JSON(http.StatusOK, gin.H{"msg": "failed"})
			return
		}
		fmt.Printf("Command output: %s\n", output)
		c.JSON(http.StatusOK, gin.H{"msg": "success"})
	})

	router.GET("escrow_pool_balance", func(c *gin.Context) {
		var pool Account
		if err := db.DB.Model(&pool).Where("addr = ?", global.EscrowPool).First(&pool).Error; err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to fetch escrow pool"})
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"addr":    pool.Addr,
			"balance": WeiToBKCString(ValueToWei(pool.Value)), //前端用BKC展示
		})
	})

	router.POST("make_incentive_table", func(c *gin.Context) {
		var req DistributeReq
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
			return
		}
		strategy, err := parseDistributeStrategy(req.Strategy)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid strategy"})
			return
		}

		var pool Account
		if err := db.DB.Model(&pool).Where("addr = ?", global.EscrowPool).First(&pool).Error; err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to fetch escrow pool"})
			return
		}

		amount, err := BKCStringToWei(req.Amount)
		if err != nil || amount.Sign() <= 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please enter valid numbers"})
			return
		}
		poolWei := ValueToWei(pool.Value)
		if amount.Cmp(poolWei) > 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Insufficient pool balance"})
			return
		}

		var targets []string
		switch req.Targets.Type {
		case "Senior":
			nodes, err := SelectNodes[Node2](req.Targets.ActiveSince)
			if err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to fetch such targets"})
				return
			}
			if len(nodes) < 3 {
				c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("Too few qualified senior nodes: %d", len(nodes))})
				return
			}
			targets = make([]string, 0, len(nodes))
			for _, node := range nodes {
				targets = append(targets, node.PublicKey)
			}
		case "Junior":
			nodes, err := SelectNodes[Node](req.Targets.ActiveSince)
			if err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to fetch such targets"})
				return
			}
			targets = make([]string, 0, len(nodes))
			for _, node := range nodes {
				targets = append(targets, node.PublicKey)
			}
			if len(nodes) < 12 {
				c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("Too few qualified junior nodes: %d", len(nodes))})
				return
			}
		default:
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid target type"})
			return
		}
		if len(targets) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "No active targets found"})
			return
		}

		var incentiveTable IncentiveTable
		if _, err := incentiveTable.Make(pool, targets, amount, strategy); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("Failed to build incentive table: %v", err)})
			return
		}

		tableID := newIncentivePreviewID()
		incentivePreviewStore.Lock()
		incentivePreviewStore.Items[tableID] = incentivePreviewEntry{
			Table:     cloneIncentiveTable(incentiveTable),
			CreatedAt: time.Now(),
		}
		incentivePreviewStore.Unlock()

		addrs := make([]string, 0, len(incentiveTable.Mapping))
		for addr := range incentiveTable.Mapping {
			addrs = append(addrs, addr)
		}
		sort.Strings(addrs)

		items := make([]IncentivePreviewItem, 0, len(addrs))
		for _, addr := range addrs {
			items = append(items, IncentivePreviewItem{
				Addr:   addr,
				Amount: WeiToBKCString(incentiveTable.Mapping[addr]),
			})
		}

		c.JSON(http.StatusOK, gin.H{
			"table_id":     tableID,
			"strategy":     req.Strategy,
			"total_amount": WeiToBKCString(amount),
			"count":        len(items),
			"items":        items,
		})
	})

	router.POST("manual_distribute", func(c *gin.Context) {
		var req DistributeReq
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
			return
		}
		if req.TableID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Missing incentive table id"})
			return
		}

		table, ok := getIncentivePreview(req.TableID)
		if !ok {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid or expired incentive table"})
			return
		}

		// 确认派发时再次校验当前状态，避免预览之后数据发生变化导致表不再成立。
		var pool Account
		if err := db.DB.Model(&pool).Where("addr = ?", global.EscrowPool).First(&pool).Error; err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to fetch escrow pool"})
			return
		}
		if table.TotalAmount == nil || table.TotalAmount.Sign() <= 0 || len(table.Mapping) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid incentive table"})
			return
		}
		if table.TotalAmount.Cmp(ValueToWei(pool.Value)) > 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Insufficient pool balance"})
			return
		}

		table.Pool = pool
		if err := Distribute(&table); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("Failed to distribute. Reason: %v", err)})
			return
		}
		deleteIncentivePreview(req.TableID)
		c.JSON(http.StatusOK, gin.H{"msg": "Distribute task done."})
	})

	router.POST("eth_getCode", eth_getCode)
	router.POST("eth_getBlockByNumber", eth_getBlockByNumber)
	router.POST("eth_getBlockByHash", eth_getBlockByHash)
	router.POST("eth_blockNumber", eth_blockNumber)
	router.POST("eth_getTransactionReceipt", eth_getTransactionReceipt)
	router.POST("eth_estimateGas", eth_estimateGas)
	router.POST("eth_getTransactionCount", eth_getTransactionCount)
	router.POST("eth_getTransactionByHash", eth_getTransactionByHash)
	router.POST("eth_call", eth_call)
	router.POST("eth_sendTransaction", eth_sendTransaction)
	router.POST("eth_sendRawTransaction", eth_sendRawTransaction)
	router.POST("reportblock", reportblock)
	router.POST("reportblock_senior", reportblock_senior)
	router.POST("reward_wallet", reward_wallet)
	router.POST("query-g", queryacc)
	router.POST("query-g2", queryacc2)
	router.GET("query-g3", queryacc3)
	router.POST("query-g10", queryacc10)
	router.POST("sendtx", sendtx)
	router.POST("join", join)
	router.POST("join2", join2)
	router.POST("join2_senior", join2_senior)
	router.POST("beat", beat)
	router.GET("ws", ws)
	router.GET("ws2", ws2)
	router.GET("ws2_senior", ws2_senior)
	router.POST("getProblem", getProblem)

	router.POST("queryisbroker", queryisbroker)
	router.POST("applybroker", applybroker)
	router.POST("stake", stake)
	router.POST("querybrokerprofit", querybrokerprofit)
	router.POST("withdrawbroker", withdrawbroker)

	router.POST("claim", claim)
	router.GET("claim2", claim2)
	router.POST("applyclaim", applyclaim)
	router.GET("queryclaim", queryclaim)
	router.GET("managequeryclaimfdsh23dsaka2ahja1rS", managequeryclaim)
	router.GET("managequeryclaim2fdsh23dsaka2ahja1rS", managequeryclaim2)

	router.POST("managequeryclaim2gwefesk76sg", rejectclaim)
	router.POST("managequeryclaim2gwefesk76sg2", acceptclaim)
	router.GET("getcode", getcode)
	router.GET("getversion", GetVersion)

	router.GET("getcontractinvoke_bhajbkeiwa782ygjkswiu", getcontractinvoke)
	router.GET("getwls_fhisajejdha", getwls)
	router.GET("getwls_fhisajejdha1", getwlj)

	// 旧账户升级，相关接口
	router.GET("get_oldAccount", getOldAccount)
	router.POST("transferToNewAccount", transferToNewAccount)

	err := http.ListenAndServe(":56741", r)
	if err != nil {
		fmt.Println(err)
	}
}

func CorsConfig() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*") // 可将将 * 替换为指定的域名
		c.Header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, UPDATE")
		c.Header("Access-Control-Allow-Headers", "*")
		c.Header("Access-Control-Expose-Headers", "*")
		c.Header("Access-Control-Allow-Credentials", "true")
		c.Writer.Header().Set("Access-Control-Max-Age", "86400")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(200)
		} else {
			c.Next()
		}
	}
}
