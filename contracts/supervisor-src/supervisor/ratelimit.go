package supervisor

import (
	"golang.org/x/time/rate"
	"sync"
)

type rateLimiter struct {
	ip       string
	limiters [2]*rate.Limiter
}
type rateLimiter2 struct {
	ip       string
	limiters *rate.Limiter
}

var (
	ipLimiters = struct {
		sync.RWMutex
		m map[string]*rateLimiter
	}{m: make(map[string]*rateLimiter)}
	ipLimiters2 = struct {
		sync.RWMutex
		m map[string]*rateLimiter2
	}{m: make(map[string]*rateLimiter2)}
)

func getOrNewRateLimiter2(ip string) *rateLimiter2 {
	ipLimiters2.RLock()
	limiter, exists := ipLimiters2.m[ip]
	ipLimiters2.RUnlock()

	if !exists {
		ipLimiters2.Lock()
		defer ipLimiters2.Unlock()

		limiter = &rateLimiter2{
			ip:       ip,
			limiters: rate.NewLimiter(40, 400),
		}
		ipLimiters2.m[ip] = limiter
	}

	return limiter
}

// 获取或创建针对某个 IP 的限流器
func getOrNewRateLimiter(ip string) *rateLimiter {
	ipLimiters.RLock()
	limiter, exists := ipLimiters.m[ip]
	ipLimiters.RUnlock()

	if !exists {
		ipLimiters.Lock()
		defer ipLimiters.Unlock()

		limiter = &rateLimiter{
			ip: ip,
			limiters: [2]*rate.Limiter{
				rate.NewLimiter(3, 100),
				rate.NewLimiter(3, 100),
			},
		}
		ipLimiters.m[ip] = limiter
	}

	return limiter
}