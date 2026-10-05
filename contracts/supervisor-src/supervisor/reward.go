package supervisor
func GetReward(count int64) float64 {
	if count == 0 {
		return 10
	}
	if count < 10 {
		return 9
	}
	if count < 100 {
		return 8
	}
	if count < 1000 {
		return 7
	}
	if count < 2000 {
		return 6
	}
	if count < 3000 {
		return 5
	}
	if count < 4000 {
		return 4
	}
	if count < 8000 {
		return 3
	}
	if count < 40000 {
		return 2
	}
	if count < 100000 {
		return 1
	}
	if count < 1000000 {
		return 0.5
	}
	return 0.1
}
