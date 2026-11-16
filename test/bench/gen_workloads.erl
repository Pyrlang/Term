%% Writes the shaped benchmark workloads of plan step TERM-21: terms that
%% look like Pyrlang's traffic, encoded by this OTP (never by our encoder).
%%
%%   erl -noshell -pa Dir -run gen_workloads main OutDir -s init stop
%%
%% Each workload is a directory OutDir/<name>/ holding one or more .etf
%% files; bench_otp.erl and bench_codec.py time all files of a directory as
%% one call. run.py adds the fixture corpora as two more directories.
-module(gen_workloads).

-export([main/1]).

main([OutDir]) ->
    lists:foreach(fun({Name, Term}) -> write(OutDir, Name, Term) end, workloads()),
    io:format("wrote ~b workloads to ~ts~n", [length(workloads()), OutDir]).

write(OutDir, Name, Term) ->
    File = filename:join([OutDir, Name, Name ++ ".etf"]),
    ok = filelib:ensure_dir(File),
    Bin = term_to_binary(Term),
    Term = binary_to_term(Bin),
    ok = file:write_file(File, Bin).

workloads() ->
    Pid = pid(1234, 5),
    [%% REG_SEND control tuple, the head of every message to a named process.
     {"dist_control", {6, Pid, '', rex}},
     %% What gen_server:call/2 sends since OTP 24: an alias in the tag.
     {"gen_call",
      {'$gen_call', {Pid, [alias | ref(1)]},
       {put, <<"some/key">>, #{value => 42, ttl => 3600, tags => [a, b, c]}}}},
     {"binary_1mb", binary:copy(list_to_binary(lists:seq(0, 255)), 4096)},
     {"list_100k_ints", lists:seq(1, 100000)},
     {"string_65535", [32 + I rem 95 || I <- lists:seq(1, 65535)]},
     {"map_10k_atom_keys",
      maps:from_list([{list_to_atom("key_" ++ integer_to_list(I)), I}
                      || I <- lists:seq(1, 10000)])},
     {"atoms_200_unicode",
      [list_to_atom([16#43F, 16#440, 16#438 | integer_to_list(I)])
       || I <- lists:seq(1, 200)]},
     {"bignums_1000", [(1 bsl (64 + I)) + I || I <- lists:seq(1, 1000)]},
     {"pids_refs_1000", [{pid(I, I * 7), ref(I)} || I <- lists:seq(1, 1000)]},
     {"nested_1000", lists:foldl(fun(_, Acc) -> [Acc] end, [], lists:seq(1, 1000))},
     {"floats_10k", [I * 1.5 || I <- lists:seq(1, 10000)]},
     {"tuples_10k", [{I, ok, <<"v">>} || I <- lists:seq(1, 10000)]}].

%% A pid of another node with V4 (32-bit) fields: NEW_PID_EXT.
pid(Id, Serial) ->
    binary_to_term(<<131, 88, (node_atom())/binary, Id:32, Serial:32, 16#5F3A7C01:32>>).

%% A 3-word reference of another node: NEWER_REFERENCE_EXT.
ref(N) ->
    binary_to_term(<<131, 90, 3:16, (node_atom())/binary, 16#5F3A7C01:32,
                     N:32, 16#12345678:32, 16#9ABCDEF0:32>>).

%% 'erl@127.0.0.1' as SMALL_ATOM_UTF8_EXT.
node_atom() ->
    Name = <<"erl@127.0.0.1">>,
    <<119, (byte_size(Name)), Name/binary>>.
