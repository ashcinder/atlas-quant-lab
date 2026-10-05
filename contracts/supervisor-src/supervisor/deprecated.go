package supervisor

import (
	"encoding/base64"
)

func GetBase64(c string) string {
	data := []byte(c)

	encodedString := base64.StdEncoding.EncodeToString(data)
	return encodedString
}
//func CreateCrt() (string, string, error) {
//	file1, err := os.ReadFile("C:\\Users\\1\\Desktop\\sdk-go-demo-v2.3.2\\config\\crypto-config\\1006\\ca\\ca.crt")
//	if err != nil {
//		fmt.Println(err)
//		return "", "", err
//	}
//	file2, err := os.ReadFile("C:\\Users\\1\\Desktop\\sdk-go-demo-v2.3.2\\config\\crypto-config\\1006\\ca\\ca.key")
//	if err != nil {
//		fmt.Println(err)
//		return "", "", err
//	}
//
//	caCert := string(file1)
//	caPrivateKey := string(file2)
//	orgId := "1006"
//	userName := "myuser"
//
//	certPem, privKeyStr, err := IssueCertExtend("cn", "beijing", "beijing", "client", orgId, userName+".sign."+orgId, 1, caCert, caPrivateKey)
//
//	fmt.Println(certPem)
//	fmt.Println(GetBase64(certPem))
//	fmt.Println(GetBase64(privKeyStr))
//
//	return GetBase64(certPem), GetBase64(privKeyStr), nil
//
//}