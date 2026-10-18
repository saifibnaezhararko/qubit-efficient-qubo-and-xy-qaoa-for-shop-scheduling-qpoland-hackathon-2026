# Part 5 - Second milling machine: does it pay off?

40 random daily order books (4 jobs, milling is the bottleneck: F 2-3 h, T and S 1-2 h, due dates, two part families with 1 h changeovers). Each book is optimised with one and with two milling machines within the same shift (horizon = optimal one-machine makespan + 1 h) as a time-indexed QUBO solved by simulated annealing; the savings use the CP-SAT optimum of the same model.

* mean saving: **10.50** cost units per day (95% CI 9.00 .. 12.12)
* estimated from the QUBO solutions alone: 10.50 (95% CI 9.00 .. 12.12) - the investment decision does not depend on which solver is used
* QUBO+SA (best of the one-hot and domain-wall QUBO) found the optimum in 100% of the 80 solves; mean relative gap 0.0%
* the parallel machine costs qubits: 116.3 -> 161.7 qubits on average (each milling operation gets a unit choice)
* **illustrative economics** (all assumptions are CLI parameters): 1 cost unit = 150.0 PLN (makespan weight 2 = 300.0 PLN per hour of shop time, tardiness weight = 150.0 PLN per weighted hour late), 250 working days/year, machine 450,000 PLN -> **393,750 PLN/year, payback 1.1 years**

| book | optimum 1 F | optimum 2 F | saving | qubits 1 F | qubits 2 F | QUBO 1 F | QUBO 2 F |
|---|---|---|---|---|---|---|---|
| 0 | 34 | 22 | 12 | 121 | 166 | 34.0 | 22.0 |
| 1 | 30 | 24 | 6 | 126 | 169 | 30.0 | 24.0 |
| 2 | 51 | 32 | 19 | 140 | 189 | 51.0 | 32.0 |
| 3 | 29 | 22 | 7 | 108 | 156 | 29.0 | 22.0 |
| 4 | 24 | 20 | 4 | 113 | 152 | 24.0 | 20.0 |
| 5 | 26 | 22 | 4 | 104 | 152 | 26.0 | 22.0 |
| 6 | 34 | 24 | 10 | 115 | 156 | 34.0 | 24.0 |
| 7 | 37 | 25 | 12 | 131 | 182 | 37.0 | 25.0 |
| 8 | 37 | 30 | 7 | 48 | 135 | 37.0 | 30.0 |
| 9 | 39 | 20 | 19 | 127 | 174 | 39.0 | 20.0 |
| 10 | 36 | 23 | 13 | 121 | 174 | 36.0 | 23.0 |
| 11 | 37 | 31 | 6 | 119 | 160 | 37.0 | 31.0 |
| 12 | 41 | 29 | 12 | 126 | 169 | 41.0 | 29.0 |
| 13 | 28 | 20 | 8 | 114 | 161 | 28.0 | 20.0 |
| 14 | 29 | 24 | 5 | 116 | 155 | 29.0 | 24.0 |
| 15 | 39 | 27 | 12 | 129 | 174 | 39.0 | 27.0 |
| 16 | 39 | 26 | 13 | 147 | 199 | 39.0 | 26.0 |
| 17 | 34 | 25 | 9 | 125 | 168 | 34.0 | 25.0 |
| 18 | 24 | 22 | 2 | 101 | 135 | 24.0 | 22.0 |
| 19 | 39 | 24 | 15 | 120 | 166 | 39.0 | 24.0 |
| 20 | 44 | 24 | 20 | 112 | 161 | 44.0 | 24.0 |
| 21 | 27 | 20 | 7 | 109 | 148 | 27.0 | 20.0 |
| 22 | 34 | 22 | 12 | 132 | 178 | 34.0 | 22.0 |
| 23 | 52 | 30 | 22 | 120 | 164 | 52.0 | 30.0 |
| 24 | 29 | 21 | 8 | 96 | 131 | 29.0 | 21.0 |
| 25 | 42 | 27 | 15 | 138 | 186 | 42.0 | 27.0 |
| 26 | 36 | 20 | 16 | 112 | 152 | 36.0 | 20.0 |
| 27 | 35 | 23 | 12 | 118 | 169 | 35.0 | 23.0 |
| 28 | 30 | 20 | 10 | 117 | 161 | 30.0 | 20.0 |
| 29 | 24 | 20 | 4 | 107 | 148 | 24.0 | 20.0 |
| 30 | 39 | 29 | 10 | 106 | 151 | 39.0 | 29.0 |
| 31 | 34 | 28 | 6 | 104 | 143 | 34.0 | 28.0 |
| 32 | 36 | 27 | 9 | 122 | 164 | 36.0 | 27.0 |
| 33 | 43 | 26 | 17 | 115 | 161 | 43.0 | 26.0 |
| 34 | 42 | 24 | 18 | 126 | 174 | 42.0 | 24.0 |
| 35 | 28 | 20 | 8 | 110 | 148 | 28.0 | 20.0 |
| 36 | 30 | 24 | 6 | 97 | 139 | 30.0 | 24.0 |
| 37 | 31 | 25 | 6 | 124 | 168 | 31.0 | 25.0 |
| 38 | 37 | 22 | 15 | 118 | 169 | 37.0 | 22.0 |
| 39 | 26 | 22 | 4 | 120 | 161 | 26.0 | 22.0 |
