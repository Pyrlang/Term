%% Times OTP's own binary_to_term/1 and term_to_binary/1 on the benchmark
%% workloads (plan step TERM-21): the reference for "fast enough".
%%
%%   erl +S 1 -noshell -pa Dir -run bench_otp main WorkDir Seconds -s init stop
%%
%% WorkDir has one directory per workload with its .etf files; one call
%% handles every file of the workload. Seconds is the time budget per
%% workload and operation. Prints one JSON object on stdout; the layout is
%% the same as bench_codec.py's.
-module(bench_otp).

-export([main/1]).

%% A sample is a batch of calls that takes at least a tenth of the budget,
%% within these bounds, so that the clock's resolution (0.1 ms for OTP on
%% Windows) and the timing overhead do not show.
-define(MIN_BATCH_NS, 1000000).
-define(MAX_BATCH_NS, 20000000).
-define(MIN_SAMPLES, 5).
-define(MAX_SAMPLES, 2000).

main([WorkDir, SecondsStr]) ->
    Budget = round(list_to_float(SecondsStr) * 1.0e9),
    {ok, Names0} = file:list_dir(WorkDir),
    Names = [N || N <- lists:sort(Names0), filelib:is_dir(filename:join(WorkDir, N))],
    Results = [workload(WorkDir, N, Budget) || N <- Names],
    io:put_chars(
      ["{\"impl\": \"otp\", \"otp_release\": \"", erlang:system_info(otp_release),
       "\", \"erts\": \"", erlang:system_info(version),
       "\", \"schedulers\": ", integer_to_list(erlang:system_info(schedulers)),
       ", \"results\": [", lists:join(", ", lists:append(Results)), "]}\n"]).

workload(WorkDir, Name, Budget) ->
    Files = lists:sort(filelib:wildcard(filename:join([WorkDir, Name, "*.etf"]))),
    Bins = [begin {ok, B} = file:read_file(F), B end || F <- Files],
    Terms = [binary_to_term(B) || B <- Bins],
    Encoded = [term_to_binary(T) || T <- Terms],
    [json(Name, "decode", iolist_size(Bins),
          measure(fun() -> decode_all(Bins, []) end, Budget)),
     json(Name, "encode", iolist_size(Encoded),
          measure(fun() -> encode_all(Terms, 0) end, Budget))].

%% Both loops return something made of every result: the compiler removes a
%% term_to_binary/1 call whose value is not used.
decode_all([B | Bs], _) -> decode_all(Bs, binary_to_term(B));
decode_all([], Last) -> Last.

encode_all([T | Ts], Size) -> encode_all(Ts, Size + byte_size(term_to_binary(T)));
encode_all([], Size) -> Size.

%% Runs in a fresh process with a large heap so that garbage of an earlier
%% workload is not collected inside this one's timed loops.
measure(Fun, Budget) ->
    Self = self(),
    {Pid, MRef} =
        spawn_opt(fun() -> Self ! {self(), measure_here(Fun, Budget)} end,
                  [monitor, {min_heap_size, 4000000}]),
    receive
        {Pid, Samples} ->
            erlang:demonitor(MRef, [flush]),
            Samples;
        {'DOWN', MRef, process, Pid, Reason} ->
            error({bench_failed, Reason})
    end.

measure_here(Fun, Budget) ->
    BatchNs = max(?MIN_BATCH_NS, min(?MAX_BATCH_NS, Budget div 10)),
    Batch = calibrate(Fun, 1, BatchNs),
    _ = batch_ns(Fun, Batch),
    Deadline = erlang:monotonic_time(nanosecond) + Budget,
    sample(Fun, Batch, Deadline, 0, []).

%% The number of calls that fill BatchNs (also the warm-up).
calibrate(Fun, Batch, BatchNs) ->
    Ns = batch_ns(Fun, Batch),
    if
        Ns >= BatchNs -> Batch;
        Ns * 2 >= BatchNs -> Batch * 2;
        true ->
            Wanted = (Batch * BatchNs) div max(Ns, 1),
            calibrate(Fun, min(Batch * 100, max(Batch * 2, Wanted)), BatchNs)
    end.

sample(Fun, Batch, Deadline, N, Acc) ->
    Ns = batch_ns(Fun, Batch),
    Acc1 = [Ns / Batch | Acc],
    Now = erlang:monotonic_time(nanosecond),
    if
        N + 1 >= ?MAX_SAMPLES -> Acc1;
        N + 1 >= ?MIN_SAMPLES, Now >= Deadline -> Acc1;
        true -> sample(Fun, Batch, Deadline, N + 1, Acc1)
    end.

batch_ns(Fun, Batch) ->
    T0 = erlang:monotonic_time(nanosecond),
    repeat(Fun, Batch),
    erlang:monotonic_time(nanosecond) - T0.

repeat(_, 0) -> ok;
repeat(Fun, N) -> Fun(), repeat(Fun, N - 1).

json(Name, Op, Bytes, Samples) ->
    Sorted = lists:sort(Samples),
    io_lib:format(
      "{\"workload\": \"~ts\", \"op\": \"~ts\", \"bytes\": ~b, \"samples\": ~b, "
      "\"median_ns\": ~.1f, \"p95_ns\": ~.1f}",
      [Name, Op, Bytes, length(Sorted), percentile(Sorted, 50), percentile(Sorted, 95)]).

%% Nearest-rank percentile of a sorted list.
percentile(Sorted, P) ->
    N = length(Sorted),
    lists:nth(max(1, min(N, (P * N + 99) div 100)), Sorted).
