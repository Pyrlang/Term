%%
%% %CopyrightBegin%
%%
%% SPDX-License-Identifier: Apache-2.0
%%
%% Copyright Ericsson AB 1997-2026. All Rights Reserved.
%% Copyright 2026, the Pyrlang authors (selection, adaptation, glue code).
%%
%% Licensed under the Apache License, Version 2.0 (the "License");
%% you may not use this file except in compliance with the License.
%% You may obtain a copy of the License at
%%
%%     http://www.apache.org/licenses/LICENSE-2.0
%%
%% Unless required by applicable law or agreed to in writing, software
%% distributed under the License is distributed on an "AS IS" BASIS,
%% WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
%% See the License for the specific language governing permissions and
%% limitations under the License.
%%
%% %CopyrightEnd%
%%

%% Terms and byte vectors copied from OTP's own test suites (OTP maint-29,
%% checked out in reference/otp), for the codec vector tests (plan step
%% TERM-04). gen_fixtures.erl writes them to test/fixtures/otp/.
%%
%% Code copied from:
%%   erts/emulator/test/binary_SUITE.erl
%%   erts/emulator/test/node_container_SUITE.erl
%%   erts/emulator/test/erts_test_utils.erl
%%   lib/erl_interface/test/ei_encode_SUITE.erl
%%   lib/erl_interface/test/ei_decode_SUITE.erl
%%   lib/erl_interface/test/ei_decode_encode_SUITE.erl
%% Each group below starts with a "From <suite>:<case>" comment. Changes
%% from the originals: test cases hand each term to a collector instead of
%% checking it; random node names are fixed; rand is seeded; ports opened
%% with open_port/2 are replaced by hd(erlang:ports()); deep/1 nests 200
%% levels instead of 1 000 000 (the full depth is a resource-limit test,
%% TERM-09); the mk_* constructors also record the bytes they build, so the
%% old tags they use (PID_EXT, PORT_EXT, REFERENCE_EXT, NEW_REFERENCE_EXT)
%% become raw vectors.

-module(otp_vectors).

-export([groups/0, sleeper/0]).

%% Copied code keeps OTP's style (`Test_Func(Bin0 = ...)` binds in a call).
-compile([nowarn_export_var_subexpr]).

%% One group of vectors: {Origin, Items}. Origin is "<suite>:<case>". An
%% item is {t2b, Term, Opts} (OTP encodes Term with term_to_binary(Term,
%% Opts)) or {raw, Bin, Features} (Bin is written as is; Features names
%% encodings the term alone does not show, e.g. reference_ext).
-type item() :: {t2b, term(), list()} | {raw, binary(), [atom()]}.

%% From binary_SUITE.erl
-define(heap_binary_size, 64).

%% From ei_decode_encode_SUITE.erl and erts_test_utils.erl
-define(VERSION_MAGIC,       131).
-define(ATOM_EXT,            100).
-define(REFERENCE_EXT,       101).
-define(PORT_EXT,            102).
-define(PID_EXT,             103).
-define(NEW_REFERENCE_EXT,   114).
-define(NEW_PID_EXT,         $X).
-define(NEW_PORT_EXT,        $Y).
-define(NEWER_REFERENCE_EXT, $Z).
-define(V4_PORT_EXT,         $x).
-define(OLD_MAX_PIDS_PORTS, ((1 bsl 28) - 1)).
-define(OLD_MAX_PID_NUM, ((1 bsl 15) - 1)).
-define(OLD_MAX_PID_SER, ((1 bsl 13) - 1)).

%% From binary_SUITE.erl (erl_ext_dist tags and the flatmap size limit)
-define(MAP_EXT, 116).
-define(SMALL_INTEGER_EXT, 97).
-define(NIL, 106).
-define(MAP_SMALL_MAP_LIMIT, 32).

-if(?OTP_RELEASE >= 29).
%% From binary_SUITE.erl: native records used by test_terms/1.
-record #empty{}.
-record #order{zzzz=0, true=1, aaaa=2, wwww=3, z=4, a=5}.
-endif.

-spec groups() -> [{string(), [item()]}].
groups() ->
    %% Deterministic "random" pids and ports in the ei groups.
    _ = rand:seed(exsss, {16#5059, 16#524c, 16#414e}),
    %% A bare `erl -noshell` has no ports; the suites take hd(erlang:ports()).
    {ok, Socket} = gen_udp:open(0),
    true = is_port(Socket),
    [group("binary_SUITE:terms", fun terms/0),
     group("binary_SUITE:terms_float", fun terms_float/0),
     group("binary_SUITE:deep", fun deep/0),
     group("binary_SUITE:unsorted_map_in_map", fun unsorted_map_in_map/0),
     group("binary_SUITE:robustness", fun robustness/0),
     group("node_container_SUITE:term_to_binary_to_term_eq",
           fun term_to_binary_to_term_eq/0),
     group("node_container_SUITE:round_trip_eq", fun round_trip_eq/0),
     group("node_container_SUITE:huge_ref", fun huge_ref/0),
     group("ei_encode_SUITE", fun ei_encode/0),
     group("ei_decode_SUITE", fun ei_decode/0),
     group("ei_decode_encode_SUITE:test_ei_decode_encode",
           fun test_ei_decode_encode/0)].

%% ---------------------------------------------------------------------------
%% Collector glue (ours, not from OTP)

%% Runs Fun, which adds items with add/2 and raw/2, and returns them in order.
group(Origin, Fun) ->
    put(items, []),
    Fun(),
    {Origin, lists:reverse(erase(items))}.

add(Term, Opts) ->
    put(items, [{t2b, Term, Opts} | get(items)]),
    ok.

%% The Test_Func handed to OTP's term generators.
add(Term) ->
    add(Term, []).

raw(Bin, Features) when is_binary(Bin) ->
    _ = binary_to_term(Bin),                    % OTP must accept it
    put(items, [{raw, Bin, Features} | get(items)]),
    ok.

%% A byte vector with the term OTP decodes it to.
raw_eq(Bin, Term) ->
    Term = binary_to_term(Bin),
    raw(Bin, []).

%% ---------------------------------------------------------------------------
%% From binary_SUITE:terms
%% terms/1 encodes every term of test_terms/1 with the default options,
%% {minor_version, 1} and compressed (the same variants are emitted here;
%% gen_fixtures drops byte-identical duplicates).

terms() ->
    test_terms(fun(Term) ->
                       add(Term),
                       add(Term, [{minor_version, 1}]),
                       add(Term, [compressed])
               end).

test_terms(Test_Func) ->
    Test_Func(atom),
    Test_Func(''),
    Test_Func('a'),
    Test_Func('ab'),
    Test_Func('abc'),
    Test_Func('abcd'),
    Test_Func('abcde'),
    Test_Func('abcdef'),
    Test_Func('abcdefg'),
    Test_Func('abcdefgh'),

    Test_Func(fun() -> ok end),
    X = id([a,{b,c},c]),
    Y = id({x,y,z}),
    Z = id(1 bsl 8*257),
    Test_Func(fun() -> X end),
    Test_Func(fun() -> {X,Y} end),
    Test_Func([fun() -> {X,Y,Z} end,
               fun() -> {Z,X,Y} end,
               fun() -> {Y,Z,X} end]),

    Test_Func({trace_ts,{even_bigger,{some_data,fun() -> ok end}},{1,2,3}}),
    Test_Func({trace_ts,{even_bigger,{some_data,<<1,2,3,4,5,6,7,8,9,10>>}},
               {1,2,3}}),

    Test_Func(1),
    Test_Func(42),
    Test_Func(-23),
    Test_Func(256),
    Test_Func(25555),
    Test_Func(-3333),

    Test_Func(1.0),

    Test_Func(183749783987483978498378478393874),
    Test_Func(-37894183749783987483978498378478393874),
    Very_Big = very_big_num(),
    Test_Func(Very_Big),
    Test_Func(-Very_Big+1),

    Test_Func([]),
    Test_Func("abcdef"),
    Test_Func([a, b, 1, 2]),
    Test_Func([a|b]),
    Test_Func([make_port(), make_ref(), make_pid(), fun() -> ok end,
               Very_Big | lists:seq(1, 75)]),

    Test_Func({}),
    Test_Func({1}),
    Test_Func({a, b}),
    Test_Func({a, b, c}),
    Test_Func({make_port(), make_ref(), make_pid(), fun() -> ok end}),
    Test_Func(list_to_tuple(lists:seq(0, 255))),
    Test_Func(list_to_tuple(lists:seq(0, 256))),

    Test_Func(make_ref()),
    Test_Func([make_ref(), make_ref()]),

    Test_Func(make_port()),

    Test_Func(make_pid()),

    Test_Func(Bin0 = list_to_binary(lists:seq(0, 14))),
    Test_Func(Bin1 = list_to_binary(lists:seq(0, ?heap_binary_size))),
    Test_Func(Bin2 = list_to_binary(lists:seq(0, ?heap_binary_size+1))),
    Test_Func(Bin3 = list_to_binary(lists:seq(0, 255))),

    Test_Func(make_unaligned_sub_binary(Bin0)),
    Test_Func(make_unaligned_sub_binary(Bin1)),
    Test_Func(make_unaligned_sub_binary(Bin2)),
    Test_Func(make_unaligned_sub_binary(Bin3)),

    Test_Func(make_sub_binary(lists:seq(42, 43))),
    Test_Func(make_sub_binary([42,43,44])),
    Test_Func(make_sub_binary([42,43,44,45])),
    Test_Func(make_sub_binary([42,43,44,45,46])),
    Test_Func(make_sub_binary([42,43,44,45,46,47])),
    Test_Func(make_sub_binary([42,43,44,45,46,47,48])),
    Test_Func(make_sub_binary(lists:seq(42, 49))),
    Test_Func(make_sub_binary(lists:seq(0, 14))),
    Test_Func(make_sub_binary(lists:seq(0, ?heap_binary_size))),
    Test_Func(make_sub_binary(lists:seq(0, ?heap_binary_size+1))),
    Test_Func(make_sub_binary(lists:seq(0, 255))),

    Test_Func(make_unaligned_sub_binary(lists:seq(42, 43))),
    Test_Func(make_unaligned_sub_binary([42,43,44])),
    Test_Func(make_unaligned_sub_binary([42,43,44,45])),
    Test_Func(make_unaligned_sub_binary([42,43,44,45,46])),
    Test_Func(make_unaligned_sub_binary([42,43,44,45,46,47])),
    Test_Func(make_unaligned_sub_binary([42,43,44,45,46,47,48])),
    Test_Func(make_unaligned_sub_binary(lists:seq(42, 49))),
    Test_Func(make_unaligned_sub_binary(lists:seq(0, 14))),
    Test_Func(make_unaligned_sub_binary(lists:seq(0, ?heap_binary_size))),
    Test_Func(make_unaligned_sub_binary(lists:seq(0, ?heap_binary_size+1))),
    Test_Func(make_unaligned_sub_binary(lists:seq(0, 255))),

    %% Bit level binaries.
    Test_Func(<<1:1>>),
    Test_Func(<<2:2>>),
    Test_Func(<<42:10>>),
    Test_Func(list_to_bitstring([<<5:6>>|lists:seq(0, 255)])),

    %% Funs in a list.
    Test_Func(F = fun(A) -> 42*A end),
    Test_Func(lists:duplicate(32, F)),

    %% External funs in a list.
    Test_Func(FF = fun binary_SUITE:all/0),
    Test_Func(lists:duplicate(32, FF)),

    %% Maps.
    SmallMap = #{a => 1, b => 2, c => 3},
    LargeMap1 = maps:from_list([{list_to_atom(integer_to_list(36#cafe+N*N*N, 36)),N} ||
                                   N <- lists:seq(1, 33)]),
    LargeMap2 = maps:from_list([{list_to_atom(integer_to_list(36#dead+N, 36)),N} ||
                                   N <- lists:seq(1, 50)]),
    MapWithMap = LargeMap1#{SmallMap => a, LargeMap1 => LargeMap2, LargeMap2 => LargeMap1,
                            [LargeMap1,LargeMap2] => LargeMap1,
                            <<"abc">> => SmallMap, <<"qrs">> => LargeMap1,
                            <<"xyz">> => LargeMap2 },
    Test_Func(#{}),
    Test_Func(SmallMap),
    Test_Func(LargeMap1),
    Test_Func(LargeMap2),
    Test_Func(MapWithMap),

    %% Native records (moved into a helper so older OTP can compile this).
    native_record_terms(Test_Func, SmallMap, LargeMap1, MapWithMap),

    ok.

-if(?OTP_RELEASE >= 29).
native_record_terms(Test_Func, SmallMap, LargeMap1, MapWithMap) ->
    Test_Func(#empty{}),
    OrderRec = #order{zzzz=SmallMap, true=LargeMap1, aaaa=MapWithMap},
    Test_Func(#order{}),
    Test_Func(OrderRec),
    Test_Func(#order{z=OrderRec}),
    Test_Func({a, #order{z=#order{}}, b}).
-else.
native_record_terms(_Test_Func, _SmallMap, _LargeMap1, _MapWithMap) ->
    ok.
-endif.

%% From binary_SUITE:terms_float (default encoding and FLOAT_EXT).
terms_float() ->
    test_floats(fun(Term) ->
                        add(Term),
                        add(Term, [{minor_version, 0}])
                end).

test_floats(Test_Func) ->
    Test_Func(5.5),
    Test_Func(-15.32),
    Test_Func(1.2435e25),
    Test_Func(1.2333e-20),
    Test_Func(199.0e+15),
    ok.

very_big_num() ->
    very_big_num(33, 1).

very_big_num(Left, Result) when Left > 0 ->
    very_big_num(Left-1, Result*256);
very_big_num(0, Result) ->
    Result.

make_port() ->
    hd(erlang:ports()).

make_pid() ->
    spawn_link(?MODULE, sleeper, []).

sleeper() ->
    receive after infinity -> ok end.

make_sub_binary(Bin) when is_binary(Bin) ->
    {_,B} = split_binary(list_to_binary([0,1,3,Bin]), 3),
    B;
make_sub_binary(List) ->
    make_sub_binary(list_to_binary(List)).

make_unaligned_sub_binary(Bin) when is_binary(Bin) ->
    erts_debug:unaligned_bitstring(Bin, 3);
make_unaligned_sub_binary(List) ->
    make_unaligned_sub_binary(list_to_binary(List)).

id(I) -> I.

%% From binary_SUITE:deep (1 000 000 levels there; 200 here).
-define(DEEP, 200).

deep() ->
    add(lists_foldl_seq(fun(E, A) ->
                                [E,A]
                        end, [], 1, ?DEEP)),
    add(lists_foldl_seq(fun(E, A) ->
                                {E,A}
                        end, [], 1, ?DEEP)),
    add(lists_foldl_seq(fun(E, A) ->
                                fun() -> {E,A} end
                        end, [], 1, ?DEEP)).

%% lists:foldl(_,_,lists:seq(_,_)) with less heap consumption
lists_foldl_seq(Fun, Acc0, N, To) when N =< To ->
    Acc1 = Fun(N, Acc0),
    lists_foldl_seq(Fun, Acc1, N+1, To);

lists_foldl_seq(_, Acc, _, _) ->
    Acc.

%% From binary_SUITE:unsorted_map_in_map (OTP-18343: an unsorted flatmap, and
%% the same flatmap as a key in a hashmap).
unsorted_map_in_map() ->
    K1 = 1,
    K2 = 2,
    true = K1 < K2,
    FMap = #{K1 => [], K2 => []},
    FMapBin = <<?MAP_EXT, 2:32,
                %% unsorted list of key/value pairs
                ?SMALL_INTEGER_EXT, K2, ?NIL,
                ?SMALL_INTEGER_EXT, K1, ?NIL>>,
    raw_eq(<<131, FMapBin/binary>>, FMap),

    HKeys = lists:seq(1, ?MAP_SMALL_MAP_LIMIT+1),
    HMap0 = maps:from_list([{K,[]} || K <- HKeys]),
    HMap0Bin = term_to_binary(HMap0),

    %% Replace last key/value pair with FMap => []
    Prologue = binary:part(HMap0Bin, 0, byte_size(HMap0Bin)-3),
    HMap1Bin = <<Prologue/binary, FMapBin/binary, ?NIL>>,
    HMap1 = binary_to_term(HMap1Bin),
    [] = maps:get(FMap, HMap1),
    raw(HMap1Bin, []).

%% From binary_SUITE:robustness (non-standard encodings never produced by
%% term_to_binary/1 but accepted by binary_to_term/1).
robustness() ->
    raw_eq(<<131,107,0,0>>, []),                       %Empty string.
    raw_eq(<<131,108,0,0,0,0,106>>, []),                %Zero-length list.
    %% {[],a} where [] is a zero-length list.
    raw_eq(<<131,104,2,108,0,0,0,0,106,100,0,1,97>>, {[],a}),
    %% {42,a} where 42 is a zero-length list with 42 in the tail.
    raw_eq(<<131,104,2,108,0,0,0,0,97,42,100,0,1,97>>, {42,a}),
    %% {{x,y},a} where {x,y} is a zero-length list with {x,y} in the tail.
    raw_eq(<<131,104,2,108,0,0,0,0,
             104,2,100,0,1,120,100,0,1,
             121,100,0,1,97>>, {{x,y},a}),
    %% Bignums fitting in 32 bits.
    raw_eq(<<131,98,127,255,255,255>>, 16#7FFFFFFF),
    raw_eq(<<131,98,255,255,255,255>>, -1).

%% ---------------------------------------------------------------------------
%% From node_container_SUITE.erl

max_internal_pids_ports() ->
    case erlang:system_info(wordsize) of
        8 -> (1 bsl 60) - 1;
        4 -> (1 bsl 28) - 1
    end.

max_pids_ports() ->
    (1 bsl 64) - 1.

max_internal_pid_num() ->
    (1 bsl 28) - 1.

max_internal_pid_ser() ->
    case erlang:system_info(wordsize) of
        8 -> (1 bsl 32) - 1;
        4 -> 0
    end.

max_pid_num() ->
    (1 bsl 32) - 1.

max_pid_ser() ->
    (1 bsl 32) - 1.

%% From node_container_SUITE:term_to_binary_to_term_eq (get_nodename() gives a
%% random name there; fixed here).
term_to_binary_to_term_eq() ->
    ThisNode = {node(), erlang:system_info(creation)},
    % Get local node containers
    LPid = self(),
    LXPid = mk_pid(ThisNode, 0, max_internal_pid_ser()),
    LX2Pid = mk_pid(ThisNode, max_internal_pid_num() - 4711, max_internal_pid_ser()),
    LPort = hd(erlang:ports()),
    LXPort = mk_port(ThisNode, 268435455),
    LX2Port = mk_port(ThisNode, max_internal_pids_ports() - 4711),
    LLRef = make_ref(),
    LHLRef = mk_ref(ThisNode, [47, 11]),
    LSRef = mk_ref(ThisNode, [4711]),
    [add(T) || T <- [LPid, LXPid, LX2Pid, LPort, LXPort, LX2Port,
                     LLRef, LHLRef, LSRef]],
    % Get remote node containers
    ttbtteq_do_remote({'ttbtteq@fix-host', 3}),
    ttbtteq_do_remote({'ttbtteq@fix-host', 4}),
    ttbtteq_do_remote({'ttbtteq@fix-host', 16#adec0ded}).

ttbtteq_do_remote(RNode) ->
    RPid = mk_pid(RNode, 4711, 1),
    RXPid = mk_pid(RNode, 32767, 8191),
    RXPid2 = mk_pid(RNode, max_pid_num(), max_pid_ser()),
    RPort = mk_port(RNode, 4711),
    RXPort = mk_port(RNode, 268435455),
    RXPort2 = case RNode of
                  {_, C} when C < 4 ->
                      mk_port(RNode, 4711);
                  _ ->
                      mk_port(RNode, (1 bsl 51) + 4711)
              end,
    RXPort3 = mk_port(RNode, max_pids_ports()),
    RLRef = mk_ref(RNode, [4711, 4711, 4711]),
    RHLRef = mk_ref(RNode, [4711, 4711]),
    RSRef = mk_ref(RNode, [4711]),
    [add(T) || T <- [RPid, RXPid, RXPid2, RPort, RXPort, RXPort2, RXPort3,
                     RLRef, RHLRef, RSRef]],
    ok.

%% From node_container_SUITE:round_trip_eq (the peer node's name is fixed).
round_trip_eq() ->
    ThisNode = {node(), erlang:system_info(creation)},
    Node = 'peer@fix-host',
    SentPid = self(),
    SentXPid = mk_pid(ThisNode, 17471, max_internal_pid_ser()),
    SentXPid2 = mk_pid(ThisNode, max_internal_pid_num(), max_internal_pid_ser()),
    SentXPid3 = mk_pid({Node, 4711}, 4711, 17),
    SentXPid4 = mk_pid({Node, 4711}, max_pid_num(), max_pid_ser()),
    SentPort = hd(erlang:ports()),
    SentXPort = mk_port(ThisNode, 268435451),
    SentXPort2 = mk_port({Node, 4711}, (1 bsl 49) + 4711),
    SentXPort3 = mk_port(ThisNode, max_internal_pids_ports()),
    SentXPort4 = mk_port({Node, 4711}, max_pids_ports()),
    SentLRef = make_ref(),
    SentHLRef = mk_ref(ThisNode, [4711, 17]),
    SentSRef = mk_ref(ThisNode, [4711]),
    add({SentPid,
         SentXPid,
         SentXPid2,
         SentXPid3,
         SentXPid4,
         SentPort,
         SentXPort,
         SentXPort2,
         SentXPort3,
         SentXPort4,
         SentLRef,
         SentHLRef,
         SentSRef}).

%% From node_container_SUITE:huge_ref
huge_ref() ->
    Node = 'peer@fix-host',
    HRef = mk_ref({Node, 4711}, [4711, 705676, 3456, 1000000, 3456]),
    add(HRef).

mk_pid({NodeName, Creation}, Number, Serial) ->
    mk_ext_pid({NodeName, Creation}, Number, Serial).

mk_port({NodeName, Creation}, Number) ->
    mk_ext_port({NodeName, Creation}, Number).

mk_ref({NodeName, Creation}, Numbers) ->
    mk_ext_ref({NodeName, Creation}, Numbers).

%% ---------------------------------------------------------------------------
%% From erts_test_utils.erl (mk_ext_* also record their bytes with raw/2).

uint64_be(Uint) when is_integer(Uint), 0 =< Uint, Uint < 1 bsl 64 ->
    [(Uint bsr 56) band 16#ff,
     (Uint bsr 48) band 16#ff,
     (Uint bsr 40) band 16#ff,
     (Uint bsr 32) band 16#ff,
     (Uint bsr 24) band 16#ff,
     (Uint bsr 16) band 16#ff,
     (Uint bsr 8) band 16#ff,
     Uint band 16#ff];
uint64_be(Uint) ->
    exit({badarg, uint64_be, [Uint]}).

uint32_be(Uint) when is_integer(Uint), 0 =< Uint, Uint < 1 bsl 32 ->
    [(Uint bsr 24) band 16#ff,
     (Uint bsr 16) band 16#ff,
     (Uint bsr 8) band 16#ff,
     Uint band 16#ff];
uint32_be(Uint) ->
    exit({badarg, uint32_be, [Uint]}).

uint16_be(Uint) when is_integer(Uint), 0 =< Uint, Uint < 1 bsl 16 ->
    [(Uint bsr 8) band 16#ff,
     Uint band 16#ff];
uint16_be(Uint) ->
    exit({badarg, uint16_be, [Uint]}).

uint8(Uint) when is_integer(Uint), 0 =< Uint, Uint < 1 bsl 8 ->
    Uint band 16#ff;
uint8(Uint) ->
    exit({badarg, uint8, [Uint]}).

pid_tag(Num, Ser, Creation) when Num =< ?OLD_MAX_PID_NUM,
                                 Ser =< ?OLD_MAX_PID_SER,
                                 Creation =< 3 ->
    ?PID_EXT;
pid_tag(_Num, _Ser, _Creation) ->
    ?NEW_PID_EXT.

enc_creation(Num, Creation) when is_integer(Num),
                                 Num =< ?OLD_MAX_PIDS_PORTS,
                                 Creation =< 3 ->
    uint8(Creation);
enc_creation(Nums, Creation) when is_list(Nums),
                                  length(Nums) =< 3,
                                  Creation =< 3 ->
    uint8(Creation);
enc_creation(_Num, Creation) ->
    uint32_be(Creation).

enc_creation(Num, Ser, Creation) when Num =< ?OLD_MAX_PID_NUM,
                                      Ser =< ?OLD_MAX_PID_SER,
                                      Creation =< 3 ->
    uint8(Creation);
enc_creation(_Num, _Ser, Creation) ->
    uint32_be(Creation).

mk_ext_pid({NodeName, Creation}, Number, Serial) when is_atom(NodeName) ->
    mk_ext_pid({atom_to_list(NodeName), Creation}, Number, Serial);
mk_ext_pid({NodeName, Creation}, Number, Serial) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               pid_tag(Number, Serial, Creation),
                               ?ATOM_EXT,
                               uint16_be(length(NodeName)),
                               NodeName,
                               uint32_be(Number),
                               uint32_be(Serial),
                               enc_creation(Number, Serial, Creation)]),
               []).

port_tag(Num, Creation) when 0 =< Num, Num =< ?OLD_MAX_PIDS_PORTS, Creation =< 3 ->
    ?PORT_EXT;
port_tag(Num, _Creation) when 0 =< Num, Num =< ?OLD_MAX_PIDS_PORTS ->
    ?NEW_PORT_EXT;
port_tag(_Num, _Creation) ->
    ?V4_PORT_EXT.

mk_ext_port({NodeName, Creation}, Number) when is_atom(NodeName) ->
    mk_ext_port({atom_to_list(NodeName), Creation}, Number);
mk_ext_port({NodeName, Creation}, Number) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               port_tag(Number, Creation),
                               ?ATOM_EXT,
                               uint16_be(length(NodeName)),
                               NodeName,
                               case Number > ?OLD_MAX_PIDS_PORTS of
                                   true -> uint64_be(Number);
                                   false -> uint32_be(Number)
                               end,
                               enc_creation(Number, Creation)]),
               []).

ref_tag(Nums, Creation) when length(Nums) =< 3, Creation =< 3 -> ?NEW_REFERENCE_EXT;
ref_tag(_Nums, _Creation) -> ?NEWER_REFERENCE_EXT.

mk_ext_ref({NodeName, Creation}, Numbers) when is_atom(NodeName),
                                               is_list(Numbers) ->
    mk_ext_ref({atom_to_list(NodeName), Creation}, Numbers);
mk_ext_ref({NodeName, Creation}, [Number]) when is_list(NodeName),
                                                Creation =< 3,
                                                is_integer(Number) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ?REFERENCE_EXT,
                               ?ATOM_EXT,
                               uint16_be(length(NodeName)),
                               NodeName,
                               uint32_be(Number),
                               uint8(Creation)]),
               [reference_ext]);
mk_ext_ref({NodeName, Creation}, Numbers) when is_list(NodeName),
                                               is_list(Numbers) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ref_tag(Numbers, Creation),
                               uint16_be(length(Numbers)),
                               ?ATOM_EXT,
                               uint16_be(length(NodeName)),
                               NodeName,
                               enc_creation(Numbers, Creation),
                               lists:map(fun (N) ->
                                                 uint32_be(N)
                                         end,
                                         Numbers)]),
               []).

%% Ours: record the hand-built bytes as a raw vector and return the term.
decode_raw(Bin, Features) ->
    raw(Bin, Features),
    binary_to_term(Bin).

%% ---------------------------------------------------------------------------
%% From ei_encode_SUITE.erl: the bytes the C ei encoder writes (without the
%% 131 version byte, which ei_encode_version adds separately) and the term
%% OTP decodes them to. Duplicates across test cases are dropped later.

ei_encode() ->
    Pairs =
        [%% test_ei_encode_long, _ulong, _longlong, _ulonglong
         {<<97,0>>                        ,0},
         {<<97,255>>                      ,255},
         {<<98,256:32/big-signed-integer>>,256},
         {<<98,-1:32/big-signed-integer>> ,-1},
         {<<98, 16#07ffffff:32/big-signed-integer>>, 16#07ffffff},
         {<<98,-16#08000000:32/big-signed-integer>>,-16#08000000},
         {<<110,4,0, 0,0,0,8>>                     , 16#08000000},
         {<<110,4,1, 1,0,0,8>>                     ,-16#08000001},
         {<<110,4,0, 255,255,255,127>>             , 16#7fffffff},
         {<<110,4,1, 0,0,0,128>>                   ,-16#80000000},
         {<<98,256:32/big-unsigned-integer>>,256},
         {<<110,4,0, 0,0,0,128>>                   ,16#80000000},
         {<<110,4,0, 255,255,255,255>>             ,16#ffffffff},
         {<<110,6,0, 255,255,255,255,255,127>>     , 16#7fffffffffff},
         {<<110,6,1, 0,0,0,0,0,128>>               ,-16#800000000000},
         {<<110,8,0, 255,255,255,255,255,255,255,127>>,16#7fffffffffffffff},
         {<<110,8,1, 0,0,0,0,0,0,0,128>>           ,-16#8000000000000000},
         {<<110,6,0, 255,255,255,255,255,255>>,16#ffffffffffff},
         {<<110,8,0, 255,255,255,255,255,255,255,255>>,16#ffffffffffffffff},
         %% test_ei_encode_char
         {<<97,127>>,16#7f},
         %% test_ei_encode_misc
         {<<$w,5,"false">>,false},
         {<<$w,4,"true">> ,true},
         {<<$w,3,"foo">>,foo},
         {<<$w,0,"">>,''},
         {<<$w,12,"ÅÄÖåäö"/utf8>>,'ÅÄÖåäö'},
         {<<107,0,3,"foo">>,"foo"},
         {<<106>>,""},
         {<<107,0,6,"ÅÄÖåäö">>,"ÅÄÖåäö"},
         {<<109,0,0,0,3,"foo">>,<<"foo">>},
         {<<109,0,0,0,0,"">>,<<>>},
         {<<109,0,0,0,6,"ÅÄÖåäö">>,<<"ÅÄÖåäö">>},
         {<<104,0>>,{}},
         %% test_ei_encode_utf8_atom, _utf8_atom_len
         {<<119,2,195,133>>,'Å'},
         {<<119,1,$A>>,'A'},
         {<<119,4,195,133,195,132>>,'ÅÄ'},
         {<<119,2,$A,$B>>,'AB'}],
    [raw_eq(<<131, Bytes/binary>>, Term) || {Bytes, Term} <- Pairs],
    %% test_ei_encode_fails: the longest atoms ei accepts.
    add(list_to_atom(lists:duplicate(255, $x))),
    add(list_to_atom(lists:duplicate(255, $y))),
    add({{{{}}}}).

%% ---------------------------------------------------------------------------
%% From ei_decode_SUITE.erl: what the suite sends to the C decoder.

ei_decode() ->
    %% test_ei_decode_long, _ulong: send_integers/1 (64-bit branch)
    [add(I) || I <- [0, 255, 256, -1,
                     16#07ffffff, -16#08000000, 16#08000000, -16#08000001,
                     16#7fffffff, -16#80000000, 16#80000000, -16#80000001,
                     16#8000000000000000, 16#ffffffffffffffff,
                     16#7fffffffffffffffffffffff, -16#800000000000000000000000,
                     16#ffffffffffffffffffffffff,
                     16#7fffffffffffffffffffffffffffffff,
                     -16#80000000000000000000000000000000,
                     16#ffffffffffffffffffffffffffffffff]],
    %% test_ei_decode_longlong, _ulonglong: send_integers2/1
    [add(I) || I <- [16#ffffffff, 16#7fffffffffff, -16#800000000000,
                     16#ffffffffffff, 16#7fffffffffffffff,
                     -16#8000000000000000]],
    %% test_ei_decode_char
    add(16#7f),
    %% test_ei_decode_nonoptimal
    send_non_optimal_pos(),
    send_non_optimal_neg(),
    %% test_ei_decode_misc
    [add(T) || T <- [0.0, -1.0, 1.0, false, true, foo, '',
                     "foo", "", "ÅÄÖåäö",
                     <<"foo">>, <<>>, <<"ÅÄÖåäö">>,
                     <<1, 2, 3:5>>, <<1:1>>]],
    send_latin1_atom_as_binary("ÅÄÖåäö"),
    %% test_ei_decode_utf8_atom
    [send_latin1_atom_as_binary(S) || S <- ["å", "ä", "ö", "õ", "a", "b"]],
    [add(uc_atup(S)) || S <- [[1758], [1758,1758], [1758,1758,1758],
                              [1758,1758,1758,1758]]],
    %% test_ei_decode_iodata
    [add(T) || T <- [$a, an_atom, self(), [$a,$a], [$a|$a], [[$a|$a],$a],
                     "hej", ["hej", " ", "hopp"], <<"hopp san sa">>,
                     [$a | <<"a">>],
                     [[[["hej"]]], [$ , <<"hopp">>, $ , "san" | <<" sa">>]],
                     [[[["hej"]]], [$ , <<"hopp">>, 0, "san" | <<" sa">>]],
                     [[[["hej"]]], [$ , <<"hopp">>, 256, "san" | <<" sa">>]],
                     [[[["hej"]]], [$ , <<"hopp">>, -2, "san" | <<" sa">>]],
                     [[[["hej"]]], [$ , <<"hopp">>, $ , san | <<" sa">>]],
                     [[[["hej"]]], [$ , <<"hopp">>, $ , "san s" | $a], "  "],
                     [[[[[[[]|<<"a">>]]]]]],
                     [[[[[[[[]]]]]]],[[[],[],[]]]]]],
    %% test_ei_cmp_nc: each distinct operand (the suite sends pairs; ports it
    %% opens with open_port/2 are left out).
    Operands =
        [mk_ext_ref({a@b, 4711}, [17, 17, 17]), mk_ext_ref({a@c, 4711}, [17, 17, 17]),
         mk_ext_ref({a@d, 4711}, [17, 17, 17]), mk_ext_ref({a@bc, 4711}, [17, 17, 17]),
         mk_ext_ref({a@b, 4712}, [17, 17, 17]), mk_ext_ref({a@b, 4711}, [18, 17, 17]),
         mk_ext_ref({a@b, 4711}, [17, 18, 17]), mk_ext_ref({a@b, 4711}, [17, 17, 18]),
         mk_ext_ref({a@b, 4711}, [0, 17]), mk_ext_ref({a@b, 4711}, [18]),
         mk_ext_ref({a@b, 4711}, [17, 17]), mk_ext_ref({a@b, 4711}, [17, 18]),
         mk_ext_ref({a@b, 4711}, [0, 0, 0]), mk_ext_ref({a@b, 4711}, [17]),
         mk_ext_ref({a@b, 4711}, [0, 0, 17]), mk_ext_ref({a@b, 4711}, [18, 17]),
         mk_ext_ref({a@b, 4711}, [0, 17, 17]),
         mk_ext_pid({a@b, 4711}, 17, 17), mk_ext_pid({a@c, 4711}, 17, 17),
         mk_ext_pid({a@d, 4711}, 17, 17), mk_ext_pid({a@bc, 4711}, 17, 17),
         mk_ext_pid({a@b, 4712}, 17, 17), mk_ext_pid({a@b, 4711}, 18, 17),
         mk_ext_pid({a@b, 4711}, 17, 18),
         mk_ext_port({a@b, 4711}, 17), mk_ext_port({a@d, 4711}, 17),
         mk_ext_port({a@bc, 4711}, 17), mk_ext_port({a@b, 4712}, 17),
         mk_ext_port({a@b, 4711}, 18)],
    %% Test full 64-bit pids
    Vs = [1 bsl 30, 1 bsl 31, (1 bsl 31)-1, (1 bsl 32)-1],
    Pids = [mk_ext_pid({a@b, 4711}, A, B) || A <- Vs, B <- Vs],
    [add(T) || T <- Operands ++ Pids],
    ok.

send_non_optimal_pos() ->
    raw(<<131,97,42>>, []),
    raw(<<131,98,42:32>>, []),
    raw(<<131,110,1,0,42>>, []),
    raw(<<131,110,2,0,42,0>>, []),
    raw(<<131,110,4,0,42,0,0,0>>, []),
    raw(<<131,111,0,0,0,1,0,42>>, []),
    raw(<<131,111,0,0,0,2,0,42,0>>, []),
    raw(<<131,111,0,0,0,3,0,42,0,0>>, []),
    raw(<<131,111,0,0,0,6,0,42,0,0,0,0,0>>, []),
    ok.

send_non_optimal_neg() ->
    %   send_raw(P, <<131,97,-42>>),
    raw(<<131,98,-42:32>>, []),
    raw(<<131,110,1,1,42>>, []),
    raw(<<131,110,2,1,42,0>>, []),
    raw(<<131,110,4,1,42,0,0,0>>, []),
    raw(<<131,111,0,0,0,1,1,42>>, []),
    raw(<<131,111,0,0,0,2,1,42,0>>, []),
    raw(<<131,111,0,0,0,3,1,42,0,0>>, []),
    raw(<<131,111,0,0,0,6,1,42,0,0,0,0,0>>, []),
    ok.

send_latin1_atom_as_binary(String) ->
    raw(encode_latin1_atom(String), []).

encode_latin1_atom(String) ->
    Len = length(String),
    %% Use ATOM_EXT (not SMALL_*) to simulate old term_to_binary
    TagLen = [$d, Len bsr 8, Len band 16#ff],
    list_to_binary([131, TagLen, String]).

uc_atup(ATxt) ->
    string_to_atom(ATxt).

string_to_atom(String) ->
    Utf8List = string_to_utf8_list(String),
    Len = length(Utf8List),
    TagLen = case Len < 256 of
                 true -> [119, Len];
                 false -> [118, Len bsr 8, Len band 16#ff]
             end,
    binary_to_term(list_to_binary([131, TagLen, Utf8List])).

string_to_utf8_list([]) ->
    [];
string_to_utf8_list([CP|CPs]) when is_integer(CP),
                                   0 =< CP,
                                   CP =< 16#7F ->
    [CP | string_to_utf8_list(CPs)];
string_to_utf8_list([CP|CPs]) when is_integer(CP),
                                   16#80 =< CP,
                                   CP =< 16#7FF ->
    [16#C0 bor (CP bsr 6),
     16#80 bor (16#3F band CP) | string_to_utf8_list(CPs)];
string_to_utf8_list([CP|CPs]) when is_integer(CP),
                                   16#800 =< CP,
                                   CP =< 16#FFFF ->
    [16#E0 bor (CP bsr 12),
     16#80 bor (16#3F band (CP bsr 6)),
     16#80 bor (16#3F band CP) | string_to_utf8_list(CPs)];
string_to_utf8_list([CP|CPs]) when is_integer(CP),
                                   16#10000 =< CP,
                                   CP =< 16#10FFFF ->
    [16#F0 bor (CP bsr 18),
     16#80 bor (16#3F band (CP bsr 12)),
     16#80 bor (16#3F band (CP bsr 6)),
     16#80 bor (16#3F band CP) | string_to_utf8_list(CPs)].

%% ---------------------------------------------------------------------------
%% From ei_decode_encode_SUITE:test_ei_decode_encode (every term it sends;
%% the C side decodes and re-encodes each one).

test_ei_decode_encode() ->
    Fun1  = fun (X) -> {X,true} end,
    Fun2  = fun runner:init_per_testcase/3,
    Pid   = self(),
    Port  = hd(erlang:ports()),
    Ref   = make_ref(),
    Trace = {1,2,3,self(),4},			% FIXME how to construct?!

    BigSmallA = 1696192905348584855517250509684275447603964214606878827319923580493120589769459602596313014087329389174229999430092223701630077631205171572331191216670754029016160388576759960413039261647653627052707047,
    BigSmallB = 43581177444506616087519351724629421082877485633442736512567383077022781906420535744195118099822189576169114064491200598595995538299156626345938812352676950427869649947439032133573270227067833308153431095,
    BigSmallC = 52751775381034251994634567029696659541685100826881826508158083211003576763074162948462801435204697796532659535818017760528684167216110865807581759669824808936751316879636014972704885388116861127856231,

    BigLargeA = 1 bsl 11111 + BigSmallA,
    BigLargeB = 1 bsl 11112 + BigSmallB,
    BigLargeC = BigSmallA * BigSmallB * BigSmallC * BigSmallA,

    [add(T) || T <- [Fun1, Fun2, Pid, Port, Ref, Trace,
                     BigSmallA, BigSmallB, BigSmallC,
                     BigLargeA, BigLargeB, BigLargeC]],

    %% Test large node containers...

    ThisNode = {node(), erlang:system_info(creation)},
    TXPid = case erlang:system_info(wordsize) of
                4 -> ei_mk_pid(ThisNode, 1 bsl 27, 0);
                8 -> ei_mk_pid(ThisNode, 1 bsl 27, 1 bsl 31)
            end,
    TXPort = ei_mk_port(ThisNode, 268435455),
    TXRef = ei_mk_ref(ThisNode, [262143, 4294967295, 4294967295]),

    [add(T) || T <- [TXPid, TXPort, TXRef]],

    [begin OtherNode = {gurka@sallad, Creation},
           add(ei_mk_pid(OtherNode, 32767, 8191)),
           add(ei_mk_port(OtherNode, 268435455)),
           add(ei_mk_ref(OtherNode, [262143, 4294967295, 4294967295])),
           add(ei_mk_ref(OtherNode, [262143, 4294967295, 4294967295, 4294967294, 4294967293])),
           void
     end || Creation <- [1, 2, 3, 4, 16#adec0ded]],

    %% Full 64-bit pids
    [add(ei_mk_pid({gurka@sallad, 77},
                   rand:uniform(1 bsl Bits)-1,
                   rand:uniform(1 bsl Bits)-1))
     || Bits <- lists:seq(16,32)],

    %% Full 64-bit ports
    [add(ei_mk_port({gurka@sallad, 4711},
                    rand:uniform(1 bsl Bits)-1))
     || Bits <- lists:seq(24,40)],

    %% Unicode atoms
    [begin add(Atom),
           add(ei_mk_pid({Atom,1}, 23434, 3434)),
           add(ei_mk_port({Atom,1}, 2343434)),
           add(ei_mk_ref({Atom,1}, [262143, 8723648, 24097245])),
           void
     end || Atom <- unicode_atom_data()],

    add({}),
    add({atom, Pid, Port, Ref}),
    add([atom, Pid, Port, Ref]),
    add([atom | Fun1]),
    add(#{}),
    add(#{key => value}),
    add(maps:put(Port, Ref, #{key => value, key2 => Pid})),

    [add(<<16#dec0deb175:B/little>>) || B <- lists:seq(0,48)],

    % And last an ugly duckling to test ei_encode_bitstring with bitoffs != 0
    encode_bitstring().

encode_bitstring() ->
    Bits = <<16#18f6d4b2907e5c3a1:66>>,
    add(Bits),
    %% the sub-bitstrings the C node sends back
    receive_sub_bitstring(Bits, 0, bit_size(Bits)).

receive_sub_bitstring(_, _, NBits) when NBits < 0 ->
    ok;
receive_sub_bitstring(Bits, BitOffs, NBits) ->
    <<_:BitOffs, Sub:NBits/bits, _/bits>> = Bits,
    add(Sub),
    receive_sub_bitstring(Bits, BitOffs+1, NBits - ((NBits div 20)+1)).

%% ei_decode_encode_SUITE's own node container constructors: the node name
%% is encoded by term_to_binary (UTF-8 atom tags), creation =< 3 selects the
%% old tags.

ei_pid_tag(Creation) when Creation =< 3 -> ?PID_EXT;
ei_pid_tag(_Creation) -> ?NEW_PID_EXT.

ei_enc_creation(Creation) when Creation =< 3 -> uint8(Creation);
ei_enc_creation(Creation) -> uint32_be(Creation).

ei_mk_pid({NodeName, Creation}, Number, Serial) when is_atom(NodeName) ->
    <<?VERSION_MAGIC, NodeNameExt/binary>> = term_to_binary(NodeName),
    ei_mk_pid({NodeNameExt, Creation}, Number, Serial);
ei_mk_pid({NodeNameExt, Creation}, Number, Serial) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ei_pid_tag(Creation),
                               NodeNameExt,
                               uint32_be(Number),
                               uint32_be(Serial),
                               ei_enc_creation(Creation)]),
               []).

ei_port_tag(Num, Creation) when 0 =< Num, Num =< ?OLD_MAX_PIDS_PORTS, Creation =< 3 ->
    ?PORT_EXT;
ei_port_tag(Num, _Creation) when 0 =< Num, Num =< ?OLD_MAX_PIDS_PORTS ->
    ?NEW_PORT_EXT;
ei_port_tag(_Num, _Creation) ->
    ?V4_PORT_EXT.

ei_mk_port({NodeName, Creation}, Number) when is_atom(NodeName) ->
    <<?VERSION_MAGIC, NodeNameExt/binary>> = term_to_binary(NodeName),
    ei_mk_port({NodeNameExt, Creation}, Number);
ei_mk_port({NodeNameExt, Creation}, Number) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ei_port_tag(Number, Creation),
                               NodeNameExt,
                               case Number > ?OLD_MAX_PIDS_PORTS of
                                   true -> uint64_be(Number);
                                   false -> uint32_be(Number)
                               end,
                               ei_enc_creation(Creation)]),
               []).

ei_ref_tag(Creation) when Creation =< 3 -> ?NEW_REFERENCE_EXT;
ei_ref_tag(_Creation) -> ?NEWER_REFERENCE_EXT.

ei_mk_ref({NodeName, Creation}, Numbers) when is_atom(NodeName),
                                              is_integer(Creation),
                                              is_list(Numbers) ->
    <<?VERSION_MAGIC, NodeNameExt/binary>> = term_to_binary(NodeName),
    ei_mk_ref({NodeNameExt, Creation}, Numbers);
ei_mk_ref({NodeNameExt, Creation}, [Number]) when is_binary(NodeNameExt),
                                                  is_integer(Creation),
                                                  Creation =< 3,
                                                  is_integer(Number) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ?REFERENCE_EXT,
                               NodeNameExt,
                               uint32_be(Number),
                               uint8(Creation)]),
               [reference_ext]);
ei_mk_ref({NodeNameExt, Creation}, Numbers) when is_binary(NodeNameExt),
                                                 is_integer(Creation),
                                                 is_list(Numbers) ->
    decode_raw(list_to_binary([?VERSION_MAGIC,
                               ei_ref_tag(Creation),
                               uint16_be(length(Numbers)),
                               NodeNameExt,
                               ei_enc_creation(Creation),
                               lists:map(fun (N) ->
                                                 uint32_be(N)
                                         end,
                                         Numbers)]),
               []).

unicode_atom_data() ->
    [uc_atup(lists:seq(16#1f600, 16#1f600+254)),
     uc_atup(lists:seq(16#1f600, 16#1f600+63)),
     uc_atup(lists:seq(1, 255)),
     uc_atup(lists:seq(100, 163)),
     uc_atup(lists:seq(200, 354)),
     uc_atup(lists:seq(200, 263)),
     uc_atup(lists:seq(2000, 2254)),
     uc_atup(lists:seq(2000, 2063)),
     uc_atup(lists:seq(65500, 65754)),
     uc_atup(lists:seq(65500, 65563))
     | lists:map(fun (N) ->
                         Pow2 = (1 bsl N),
                         uc_atup(lists:seq(Pow2 - 127, Pow2 + 127))
                 end,
                 lists:seq(7, 20))
    ].
