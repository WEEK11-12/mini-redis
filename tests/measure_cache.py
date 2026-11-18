"""Explicit U7 sequential HTTP measurement; no speed-ratio pass threshold."""

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter_ns

from tests.test_cache_demo import http_json, running_demo


def main():
    results = {}
    expected_product = {'id': 1, 'name': '키보드', 'price': 50000}
    with running_demo(ttl_ms=60000) as base:
        for mode, expected_calls in [('BYPASS', 20), ('MISS', 20), ('HIT', 0)]:
            http_json(base + '/cache/delete', {})
            if mode == 'HIT':
                warmup = http_json(base + '/product')
                assert warmup['source'] == 'MISS', warmup
            before = http_json(base + '/stats')['origin_calls']
            samples = []
            for _ in range(20):
                if mode == 'MISS':
                    http_json(base + '/cache/delete', {})
                started = perf_counter_ns()
                response = http_json(base + '/product' + ('?cache=0' if mode == 'BYPASS' else ''))
                elapsed = (perf_counter_ns() - started) / 1000000
                assert response['source'] == mode, response
                assert response['product'] == expected_product, response
                samples.append({'round_trip_ms': elapsed,
                                'server_elapsed_ms': response['elapsed_ms']})
            calls = http_json(base + '/stats')['origin_calls'] - before
            assert calls == expected_calls, (mode, calls, expected_calls)
            times = [sample['round_trip_ms'] for sample in samples]
            results[mode] = {'requests': 20, 'origin_calls': calls,
                             'mean_ms': mean(times), 'median_ms': median(times),
                             'min_ms': min(times), 'max_ms': max(times), 'samples': samples}
            print(f'{mode}: 20 requests, origin={calls}, '
                  f'mean={mean(times):.3f}ms, median={median(times):.3f}ms')
    report = {'measured_at_utc': datetime.now(timezone.utc).isoformat(),
              'conditions': {'origin_delay_ms': 50, 'ttl_ms': 60000,
                             'concurrency': 1, 'requests_per_mode': 20,
                             'order': ['BYPASS', 'MISS', 'HIT'],
                             'transport': 'three local Waitress servers over HTTP',
                             'timed_region': 'client HTTP request through JSON response decoding',
                             'excluded': 'cache deletion, warmup, stats requests',
                             'clock': 'perf_counter_ns'},
              'passed': True, 'results': results}
    path = Path(__file__).resolve().parents[1] / 'history' / 'U7-cache-result.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')
    print(f'PASS: data, source, and origin counts; saved {path.name}')


if __name__ == '__main__':
    main()
