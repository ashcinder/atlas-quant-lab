package supervisor

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
)

func Test1() {
	url:="https://apis.map.qq.com/ws/location/v1/ip?key=TA2BZ-UWV6C-RQI2H-AG4O7-2ZOAE-XGFTM&ip="+"54.198.132.156"+"&output=json"
	//url := fmt.Sprintf("https://ipinfo.io/%s", ip)
	resp, err1 := http.Get(url)
	if err1 != nil {
		fmt.Println(err1)
	}
	defer resp.Body.Close()
	body, err2 := ioutil.ReadAll(resp.Body)
	if err2 != nil {
		fmt.Println(err2)
	}

	// 解析 JSON 响应
	var ipInfo Response
	err2 = json.Unmarshal(body, &ipInfo)
	if err2 != nil {
		fmt.Println(err2)
	}
	fmt.Println(ipInfo)
}
