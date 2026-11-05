// Map bounded PC aggregates to the actual ELF DWARF lines. No network or Proof.
package main

import (
	"debug/dwarf"
	"debug/elf"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
)

type sample struct {
	PC     uint64 `json:"pc"`
	Count  uint64 `json:"instruction_count"`
	Cycles uint64 `json:"raw_cycle_delta"`
}
type interval struct {
	start, end uint64
	file       string
	line       int
}
type total struct {
	File   string `json:"file"`
	Line   int    `json:"line"`
	Count  uint64 `json:"instruction_count"`
	Cycles uint64 `json:"raw_cycle_delta"`
}

func main() {
	if len(os.Args) != 3 {
		panic("pc_trace_lines USER_ELF PC_TRACE_JSON")
	}
	f, err := elf.Open(os.Args[1])
	if err != nil {
		panic(err)
	}
	defer f.Close()
	d, err := f.DWARF()
	if err != nil {
		panic(err)
	}
	var spans []interval
	r := d.Reader()
	for {
		e, err := r.Next()
		if err != nil {
			panic(err)
		}
		if e == nil {
			break
		}
		if e.Tag != dwarf.TagCompileUnit {
			continue
		}
		lr, err := d.LineReader(e)
		if err != nil {
			panic(err)
		}
		if lr != nil {
			var previous, row dwarf.LineEntry
			for {
				err := lr.Next(&row)
				if err == io.EOF {
					break
				}
				if err != nil {
					panic(err)
				}
				if previous.File != nil && !previous.EndSequence && previous.Address < row.Address {
					spans = append(spans, interval{previous.Address, row.Address, previous.File.Name, previous.Line})
				}
				previous = row
			}
		}
		r.SkipChildren()
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].start < spans[j].start })
	data, err := os.ReadFile(os.Args[2])
	if err != nil {
		panic(err)
	}
	var input struct {
		Rows             []sample `json:"rows"`
		MayIncludePaging bool     `json:"raw_cycle_deltas_may_include_paging"`
	}
	if err := json.Unmarshal(data, &input); err != nil {
		panic(err)
	}
	groups := map[string]*total{}
	for _, row := range input.Rows {
		file, line := "[unmapped/kernel]", 0
		i := sort.Search(len(spans), func(i int) bool { return spans[i].start > row.PC }) - 1
		if i >= 0 && row.PC < spans[i].end {
			file, line = spans[i].file, spans[i].line
		}
		key := fmt.Sprintf("%s:%d", file, line)
		if groups[key] == nil {
			groups[key] = &total{File: file, Line: line}
		}
		groups[key].Count += row.Count
		groups[key].Cycles += row.Cycles
	}
	rows := make([]*total, 0, len(groups))
	for _, v := range groups {
		rows = append(rows, v)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Cycles > rows[j].Cycles })
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(map[string]interface{}{
		"execution_only": true, "raw_cycle_deltas_may_include_paging": input.MayIncludePaging, "source_lines": rows}); err != nil {
		panic(err)
	}
}
