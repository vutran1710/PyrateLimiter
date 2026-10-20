# Empty BASELINE selects the default branch; CANDIDATE defaults to committed HEAD.
BASELINE ?=
CANDIDATE ?= HEAD
REDIS_CPU ?= 0
BENCH_CPU ?= 2
ROUNDS ?= 5

.PHONY: setup benchmark-redis
.DEFAULT_GOAL := benchmark-redis
.ONESHELL:
SHELL := /bin/sh
.SHELLFLAGS := -eu -c

setup:
	@if [ "$$(uname -s)" != Linux ]; then
		echo "This benchmark requires Linux (taskset and Docker CPU pinning)." >&2
		exit 1
	fi
	for tool in git docker taskset uv; do
		command -v "$$tool" >/dev/null || { echo "Missing $$tool; install it before running this benchmark." >&2; exit 1; }
	done
	docker info >/dev/null 2>&1 || { echo "Docker is unavailable; start the Docker daemon and check your access." >&2; exit 1; }
	if [ "$(REDIS_CPU)" = "$(BENCH_CPU)" ]; then
		echo "REDIS_CPU and BENCH_CPU must differ." >&2
		exit 1
	fi
	if ! taskset -c "$(REDIS_CPU)" true >/dev/null 2>&1; then
		echo "REDIS_CPU=$(REDIS_CPU) is not available." >&2
		exit 1
	fi
	if ! taskset -c "$(BENCH_CPU)" true >/dev/null 2>&1; then
		echo "BENCH_CPU=$(BENCH_CPU) is not available." >&2
		exit 1
	fi
	uv sync --locked --inexact --group all

benchmark-redis: setup
	@if [ -n "$(BASELINE)" ]; then
		baseline_ref="$(BASELINE)"
	else
		if git remote get-url upstream >/dev/null 2>&1; then
			main_remote=upstream
		else
			main_remote=origin
		fi
		git fetch --quiet "$$main_remote"
		git remote set-head "$$main_remote" --auto >/dev/null
		baseline_ref=$$(git symbolic-ref --short "refs/remotes/$$main_remote/HEAD")
	fi
	baseline_dir=$$(mktemp -d)
	candidate_dir=$$(mktemp -d)
	redis_name=pyrate-bench-redis-$$$$
	cleanup() {
		docker stop "$$redis_name" >/dev/null 2>&1 || true
		git worktree remove --force "$$baseline_dir" >/dev/null 2>&1 || rmdir "$$baseline_dir" 2>/dev/null || true
		git worktree remove --force "$$candidate_dir" >/dev/null 2>&1 || rmdir "$$candidate_dir" 2>/dev/null || true
	}
	trap cleanup EXIT
	git worktree add --quiet --detach "$$baseline_dir" "$$baseline_ref"
	git worktree add --quiet --detach "$$candidate_dir" "$(CANDIDATE)"
	printf 'Comparing %s (%s) with %s (%s)\n' \
		"$$baseline_ref" "$$(git -C "$$baseline_dir" rev-parse --short HEAD)" \
		"$(CANDIDATE)" "$$(git -C "$$candidate_dir" rev-parse --short HEAD)"
	docker run -d --rm --name "$$redis_name" -p 127.0.0.1::6379 \
		--cpuset-cpus "$(REDIS_CPU)" --cpus 1 \
		--memory 512m --memory-swap 512m redis:7.2.4 >/dev/null
	attempt=0
	until docker exec "$$redis_name" redis-cli ping >/dev/null 2>&1; do
		attempt=$$((attempt + 1))
		if [ "$$attempt" -ge 30 ]; then
			echo "Redis did not become ready:" >&2
			docker logs "$$redis_name" >&2
			exit 1
		fi
		sleep 1
	done
	redis_port=$$(docker port "$$redis_name" 6379/tcp)
	redis_port=$${redis_port##*:}
	taskset -c "$(BENCH_CPU)" uv run --locked --no-sync python benchmarks/compare_redis_weighted_put.py \
		--baseline "$$baseline_dir" --candidate "$$candidate_dir" --rounds "$(ROUNDS)" \
		--redis-url "redis://127.0.0.1:$$redis_port"
