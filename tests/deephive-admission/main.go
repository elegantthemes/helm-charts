package main

import (
	"encoding/json"
	"fmt"
	"github.com/google/cel-go/cel"
	"github.com/google/cel-go/ext"
	"os"
)

type Case struct {
	Name       string
	Expect     bool
	Activation map[string]any
}
type Fixture struct {
	Expressions []string
	Cases       []Case
}

func main() {
	var f Fixture
	b, e := os.ReadFile(os.Args[1])
	if e != nil {
		panic(e)
	}
	if e = json.Unmarshal(b, &f); e != nil {
		panic(e)
	}
	env, e := cel.NewEnv(cel.Variable("variables", cel.DynType), cel.Variable("request", cel.DynType), cel.Variable("object", cel.DynType), cel.Variable("oldObject", cel.DynType), ext.Strings())
	if e != nil {
		panic(e)
	}
	programs := []cel.Program{}
	for _, expr := range f.Expressions {
		ast, issues := env.Compile(expr)
		if issues.Err() != nil {
			panic(issues.Err())
		}
		prg, e := env.Program(ast)
		if e != nil {
			panic(e)
		}
		programs = append(programs, prg)
	}
	for _, c := range f.Cases {
		accepted := true
		for _, p := range programs {
			v, _, e := p.Eval(c.Activation)
			if e != nil || v.Value() != true {
				accepted = false
			}
		}
		if accepted != c.Expect {
			panic(fmt.Sprintf("%s: accepted=%v expected=%v", c.Name, accepted, c.Expect))
		}
		fmt.Printf("PASS %s\n", c.Name)
	}
}
