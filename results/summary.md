# Experiment summary (mean and standard deviation across runs)

## Delivery latency (ms)

Per-run mean of 20 messages; delivered_ratio is the share of messages that arrived.

| variant | condition | mean | std | count | delivered_ratio |
|---|---|---|---|---|---|
| baseline | rtt20 | 367.53 | 10.53 | 5 | 1.0 |
| baseline | rtt100 | 1701.47 | 740.52 | 5 | 1.0 |
| baseline | rtt200 | 4113.42 | 735.64 | 5 | 1.0 |
| cold | rtt20 | 415.44 | 124.53 | 5 | 1.0 |
| cold | rtt100 | 3082.97 | 1958.66 | 5 | 1.0 |
| cold | rtt200 | 5585.8 | 2174.3 | 5 | 1.0 |
| noauth | rtt20 | 269.27 | 40.05 | 5 | 1.0 |
| noauth | rtt100 | 1036.98 | 10.18 | 5 | 1.0 |
| noauth | rtt200 | 2685.35 | 134.48 | 5 | 1.0 |
| plain | rtt20 | 248.32 | 10.81 | 5 | 1.0 |
| plain | rtt100 | 535.85 | 95.82 | 5 | 1.0 |
| plain | rtt200 | 1921.56 | 692.29 | 5 | 1.0 |

## SMTP round trips and session time

rounds_x_rtt_s is the prediction: round trips times RTT.

| variant | condition | rounds | session_mean_s | session_std_s | rounds_x_rtt_s |
|---|---|---|---|---|---|
| tls_off_msgs1 | rtt20 | 7.0 | 0.318 | 0.086 | 0.14 |
| tls_off_msgs1 | rtt100 | 7.0 | 1.095 | 0.289 | 0.7 |
| tls_off_msgs1 | rtt200 | 7.0 | 2.309 | 0.621 | 1.4 |
| tls_off_msgs5 | rtt20 | 23.0 | 0.772 | 0.086 | 0.46 |
| tls_off_msgs5 | rtt100 | 23.0 | 3.157 | 0.01 | 2.3 |
| tls_off_msgs5 | rtt200 | 23.0 | 6.002 | 0.32 | 4.6 |
| tls_on_msgs1 | rtt20 | 11.0 | 0.41 | 0.097 | 0.22 |
| tls_on_msgs1 | rtt100 | 11.0 | 1.471 | 0.274 | 1.1 |
| tls_on_msgs1 | rtt200 | 11.0 | 3.396 | 0.349 | 2.2 |
| tls_on_msgs5 | rtt20 | 27.0 | 0.874 | 0.061 | 0.54 |
| tls_on_msgs5 | rtt100 | 27.0 | 3.513 | 0.038 | 2.7 |
| tls_on_msgs5 | rtt200 | 27.0 | 6.722 | 0.293 | 5.4 |

## Throughput, latency and queue backlog under loss

Loss is applied per direction on both transit interfaces.

| condition | concurrency | rate_mean | rate_std | latency_mean_ms | latency_std_ms | backlog_mean | backlog_std | delivered_mean | runs |
|---|---|---|---|---|---|---|---|---|---|
| loss0 | 1 | 9.98 | 0.3 | 360.2 | 9.61 | 2.8 | 0.45 | 100.0 | 5 |
| loss0 | 5 | 18.56 | 14.24 | 930.4 | 389.52 | 20.0 | 7.18 | 100.0 | 5 |
| loss0 | 10 | 10.15 | 2.73 | 1895.56 | 247.05 | 73.0 | 4.18 | 100.0 | 5 |
| loss0 | 20 | 9.56 | 3.29 | 2890.06 | 1399.14 | 94.4 | 2.51 | 100.0 | 5 |
| loss2 | 1 | 9.52 | 0.42 | 513.54 | 28.78 | 4.0 | 1.58 | 100.0 | 5 |
| loss2 | 5 | 12.86 | 4.02 | 1113.06 | 464.65 | 26.8 | 10.31 | 100.0 | 5 |
| loss2 | 10 | 12.58 | 6.34 | 1755.64 | 488.35 | 84.2 | 7.29 | 100.0 | 5 |
| loss2 | 20 | 9.72 | 4.53 | 1993.78 | 289.78 | 94.8 | 3.42 | 100.0 | 5 |
| loss5 | 1 | 8.02 | 0.72 | 757.92 | 63.39 | 7.2 | 0.45 | 100.0 | 5 |
| loss5 | 5 | 13.31 | 2.82 | 1383.2 | 292.04 | 44.6 | 8.59 | 100.0 | 5 |
| loss5 | 10 | 13.91 | 2.23 | 1903.08 | 495.89 | 90.0 | 4.47 | 100.0 | 5 |
| loss5 | 20 | 12.52 | 2.29 | 2110.96 | 346.71 | 96.8 | 1.92 | 100.0 | 5 |

## SPF/DKIM verdicts

match_rate is the share of runs whose verdict equals the expected one.

| condition | case | match_rate | runs |
|---|---|---|---|
| loss0 | A1 | 1.0 | 5 |
| loss0 | A2 | 1.0 | 5 |
| loss0 | A3 | 1.0 | 5 |
| loss0 | A4 | 1.0 | 5 |
| loss0 | A5 | 1.0 | 5 |
| loss0 | A6 | 1.0 | 5 |
| loss2 | A1 | 1.0 | 5 |
| loss2 | A2 | 1.0 | 5 |
| loss2 | A3 | 1.0 | 5 |
| loss2 | A4 | 1.0 | 5 |
| loss2 | A5 | 1.0 | 5 |
| loss2 | A6 | 1.0 | 5 |
| loss5 | A1 | 1.0 | 5 |
| loss5 | A2 | 1.0 | 5 |
| loss5 | A3 | 1.0 | 5 |
| loss5 | A4 | 1.0 | 5 |
| loss5 | A5 | 1.0 | 5 |
| loss5 | A6 | 1.0 | 5 |

## Observed verdict strings



| condition | case | spf | dkim |
|---|---|---|---|
| loss0 | A1 | pass | pass |
| loss0 | A2 | fail | none |
| loss0 | A3 | pass | fail |
| loss0 | A4 | pass | permerror |
| loss0 | A5 | softfail | none |
| loss0 | A6 | none | none |
| loss2 | A1 | pass | pass |
| loss2 | A2 | fail | none |
| loss2 | A3 | pass | fail |
| loss2 | A4 | pass | permerror |
| loss2 | A5 | softfail | none |
| loss2 | A6 | none | none |
| loss5 | A1 | pass | pass |
| loss5 | A2 | fail | none |
| loss5 | A3 | pass | fail |
| loss5 | A4 | pass | permerror |
| loss5 | A5 | softfail | none |
| loss5 | A6 | none | none |
