%% Copyright 2026, the Pyrlang authors
%%
%% Licensed under the Apache License, Version 2.0 (the "License");
%% you may not use this file except in compliance with the License.
%% You may obtain a copy of the License at
%%
%% http://www.apache.org/licenses/LICENSE-2.0
%%
%% Unless required by applicable law or agreed to in writing, software
%% distributed under the License is distributed on an "AS IS" BASIS,
%% WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
%% See the License for the specific language governing permissions and
%% limitations under the License.

%% Golden fixtures for the term codec tests: real OTP encodes every term, so
%% expected bytes never come from our own encoder (plan step TERM-03).
%%
%% Run from the term-src directory (or `make fixtures`):
%%
%%   erlc -o test/erl test/erl/gen_fixtures.erl test/erl/otp_vectors.erl
%%   erl -noshell -pa test/erl -run gen_fixtures main test/fixtures -s init stop
%%
%% For each fixture, writes <OutDir>/<name>.etf (term_to_binary(Term, Opts))
%% and one line in <OutDir>/MANIFEST.tsv with the columns
%%   name, otp_release, stability, source, options, features
%% `source` is the Erlang expression that built the term, re-printed by
%% erl_pp on one line (integers appear in decimal); helper calls such as
%% pid/3 refer to the functions at the end of this module. `stability` is
%% `stable` when the bytes depend only on the OTP release, or `volatile`
%% when they also depend on this module's compiled code (fun Uniq values).
%% `features` lists, comma-separated, the parts of the term that the tests
%% map to plan steps (see features/2).
%%
%% It also writes the vectors copied from OTP's test suites (otp_vectors.erl,
%% plan step TERM-04) to <OutDir>/otp/, with <OutDir>/otp/MANIFEST.tsv:
%%   name, otp_release, stability, origin, encoding, features
%% `origin` is "<suite>:<case>"; `encoding` is the term_to_binary options, or
%% `raw` for bytes written as they are (hand-built or from the C ei encoder).
%% `stability` is `volatile` when the term holds a local fun, or a pid, port
%% or reference of this node. Byte-identical vectors are written once.
%%
%% Old *.etf files in each directory are removed first, so a directory
%% always matches its manifest.

-module(gen_fixtures).

-export([main/1]).

%% {Name, Stability, Source text, Term, term_to_binary options}; ??Expr keeps
%% the expression text so the manifest shows how each term was built.
-define(F(Name, Stability, Expr), {Name, Stability, ??Expr, Expr, []}).
-define(F(Name, Stability, Expr, Opts), {Name, Stability, ??Expr, Expr, Opts}).

%% Node name used for every hand-built pid, port and reference.
-define(FIX_NODE, 'fix@host').

-if(?OTP_RELEASE >= 29).
%% Native records (EEP-79, OTP 29): exported, module-local, no fields.
-export_record([fix_exported]).
-record #fix_exported{a = 1, b = two}.
-record #fix_local{x, y = []}.
-record #fix_empty{}.
-endif.

%% Entry point for `erl -run gen_fixtures main OutDir`.
main([OutDir]) ->
    Release = erlang:system_info(otp_release),
    clean_dir(OutDir),
    Fixtures = fixtures(),
    ok = check_unique([Name || {Name, _, _, _, _} <- Fixtures]),
    Lines = [write_fixture(OutDir, Release, F) || F <- Fixtures],
    write_manifest(OutDir, "name\totp_release\tstability\tsource\toptions\tfeatures\n",
                   Lines),
    OtpDir = filename:join(OutDir, "otp"),
    clean_dir(OtpDir),
    Vectors = otp_vectors(),
    OtpLines = [write_vector(OtpDir, Release, V) || V <- Vectors],
    write_manifest(OtpDir, "name\totp_release\tstability\torigin\tencoding\tfeatures\n",
                   OtpLines),
    io:format("wrote ~b fixtures to ~ts and ~b vectors to ~ts~n",
              [length(Fixtures), OutDir, length(Vectors), OtpDir]).

clean_dir(Dir) ->
    ok = filelib:ensure_dir(filename:join(Dir, "MANIFEST.tsv")),
    Old = filelib:wildcard(filename:join(Dir, "*.etf")),
    lists:foreach(fun(F) -> ok = file:delete(F) end, Old).

write_manifest(Dir, Header, Lines) ->
    Manifest = unicode:characters_to_binary([Header | Lines]),
    ok = file:write_file(filename:join(Dir, "MANIFEST.tsv"), Manifest).

write_fixture(OutDir, Release, {Name, Stability, Source, Term, Opts}) ->
    Bin = term_to_binary(Term, Opts),
    %% A fixture that does not survive OTP's own decoder is a generator bug.
    Term = binary_to_term(Bin),
    File = filename:join(OutDir, atom_to_list(Name) ++ ".etf"),
    ok = file:write_file(File, Bin),
    io_lib:format("~ts\t~ts\t~ts\t~ts\t~0p\t~ts~n",
                  [Name, Release, Stability, pretty(Source), Opts,
                   features_text(features(Term, Opts))]).

%% The OTP-derived vectors as {Name, Origin, Encoding, Bin, Term, Features}:
%% encoded, de-duplicated by bytes, and numbered per origin.
otp_vectors() ->
    Encoded = [{Origin, encode_item(Item)}
               || {Origin, Items} <- otp_vectors:groups(), Item <- Items],
    Unique = dedupe(Encoded, #{}, []),
    number(Unique, #{}).

encode_item({t2b, Term, Opts}) ->
    Bin = term_to_binary(Term, Opts),
    Term = binary_to_term(Bin),
    {lists:flatten(io_lib:format("~0p", [Opts])), Bin, Term, features(Term, Opts)};
encode_item({raw, Bin, Extra}) ->
    Term = binary_to_term(Bin),
    {"raw", Bin, Term, lists:usort(Extra ++ features(Term, []))}.

dedupe([{_, {_, Bin, _, _}} = V | Rest], Seen, Acc) ->
    case Seen of
        #{Bin := _} -> dedupe(Rest, Seen, Acc);
        _ -> dedupe(Rest, Seen#{Bin => true}, [V | Acc])
    end;
dedupe([], _, Acc) ->
    lists:reverse(Acc).

number([{Origin, {Encoding, Bin, Term, Features}} | Rest], Counts) ->
    N = maps:get(Origin, Counts, 0) + 1,
    true = N < 1000,
    Prefix = lists:flatten(string:replace(Origin, ":", ".", all)),
    Name = lists:flatten(io_lib:format("~ts.~3..0b", [Prefix, N])),
    [{Name, Origin, Encoding, Bin, Term, Features}
     | number(Rest, Counts#{Origin => N})];
number([], _) ->
    [].

write_vector(Dir, Release, {Name, Origin, Encoding, Bin, Term, Features}) ->
    ok = file:write_file(filename:join(Dir, Name ++ ".etf"), Bin),
    Stability = case volatile(Term) of
                    true -> volatile;
                    false -> stable
                end,
    io_lib:format("~ts\t~ts\t~ts\t~ts\t~ts\t~ts~n",
                  [Name, Release, Stability, Origin, Encoding,
                   features_text(Features)]).

features_text(Features) ->
    lists:join(",", [atom_to_list(F) || F <- Features]).

%% What a term contains that the Python tests map to the plan step that
%% makes it work (test/fixture_manifest.py has the mapping):
%%   port, export_fun, local_fun, record, bitstring (not a whole number of
%%   bytes), float_ext (a float written with {minor_version, 0}),
%%   int_bits_32 (2^31 =< |I| < 2^32, except -2^31), str_latin1 (a list
%%   written as STRING_EXT holding a byte >= 128), unhashable_key (a map key
%%   whose Python value would be a list or a dict), colliding_keys (a map
%%   with keys whose Python values are equal: 1, 1.0 and true), local_ext
%%   (written with the `local` option: only this node can decode it).
features(Term, Opts) ->
    Local = [local_ext || lists:member(local, Opts)],
    lists:usort(Local ++ feat(Term, lists:member({minor_version, 0}, Opts), [])).

feat(T, _, Acc) when is_integer(T) ->
    A = abs(T),
    case A >= 1 bsl 31 andalso A < 1 bsl 32 andalso T =/= -(1 bsl 31) of
        true -> [int_bits_32 | Acc];
        false -> Acc
    end;
feat(T, true, Acc) when is_float(T) -> [float_ext | Acc];
feat(T, _, Acc) when is_float(T); is_atom(T); is_pid(T); is_reference(T);
                     is_binary(T) -> Acc;
feat(T, _, Acc) when is_port(T) -> [port | Acc];
feat(T, _, Acc) when is_bitstring(T) -> [bitstring | Acc];
feat(T, F0, Acc) when is_function(T) ->
    case erlang:fun_info(T, type) of
        {type, external} ->
            [export_fun | Acc];
        {type, local} ->
            {env, Env} = erlang:fun_info(T, env),
            feat_list(Env, F0, [local_fun | Acc])
    end;
feat(T, F0, Acc) when is_list(T) ->
    Acc1 = case is_string_ext(T) andalso lists:any(fun(C) -> C >= 128 end, T) of
               true -> [str_latin1 | Acc];
               false -> Acc
           end,
    feat_list(T, F0, Acc1);
feat(T, F0, Acc) when is_tuple(T) ->
    feat_list(tuple_to_list(T), F0, Acc);
feat(T, F0, Acc0) when is_map(T) ->
    PyKeys = [py_key(K) || K <- maps:keys(T)],
    Acc = case length(lists:usort(PyKeys)) < map_size(T) of
              true -> [colliding_keys | Acc0];
              false -> Acc0
          end,
    maps:fold(fun(K, V, A) ->
                      A1 = case py_hashable(K) of
                               true -> A;
                               false -> [unhashable_key | A]
                           end,
                      feat(V, F0, feat(K, F0, A1))
              end, Acc, T);
feat(T, F0, Acc) ->
    true = is_native_record(T),
    feat_list(record_values(T), F0, [record | Acc]).

%% Walks a list that may be improper.
feat_list([H | T], F0, Acc) -> feat_list(T, F0, feat(H, F0, Acc));
feat_list([], _, Acc) -> Acc;
feat_list(Tail, F0, Acc) -> feat(Tail, F0, Acc).

%% term_to_binary writes a list as STRING_EXT when this holds.
is_string_ext(L) -> L =/= [] andalso is_byte_list(L, 0).

is_byte_list([], N) -> N =< 65535;
is_byte_list([C | T], N) when is_integer(C), C >= 0, C =< 255 ->
    is_byte_list(T, N + 1);
is_byte_list(_, _) -> false.

%% Python decodes STRING_EXT to str, other lists to list, maps to dict.
py_hashable(K) when is_list(K) -> is_string_ext(K);
py_hashable(K) when is_map(K) -> false;
py_hashable(K) when is_tuple(K) -> lists:all(fun py_hashable/1, tuple_to_list(K));
py_hashable(_) -> true.

%% A stand-in for the Python value of a map key: keys with the same stand-in
%% are equal in Python (1 == 1.0 == True, 0.0 == -0.0, Atom("a") == "a",
%% <<5:7>> decodes to a tuple of bytes and 7), so one dict cannot hold both.
py_key(true) -> {num, 1};
py_key(false) -> {num, 0};
py_key(K) when is_integer(K) -> {num, K};
py_key(K) when is_float(K) ->
    case trunc(K) == K of
        true -> {num, trunc(K)};
        false -> {float, K}
    end;
py_key(K) when is_atom(K) -> {str, atom_to_list(K)};
py_key(K) when is_binary(K) -> {bin, K};
py_key(K) when is_bitstring(K) ->
    Bits = bit_size(K) rem 8,
    Whole = bit_size(K) - Bits,
    <<Bytes:Whole/bits, Last:Bits>> = K,
    {tuple, [{bin, <<Bytes/binary, (Last bsl (8 - Bits))>>}, {num, Bits}]};
py_key(K) when is_tuple(K) -> {tuple, [py_key(E) || E <- tuple_to_list(K)]};
py_key(K) when is_list(K) ->
    case is_string_ext(K) of
        true -> {str, K};
        false -> {other, K}
    end;
py_key(K) -> {other, K}.

-if(?OTP_RELEASE >= 29).
is_native_record(T) -> erlang:is_record(T).

%% Field values of a native record; [] for any other term.
record_values(T) ->
    case erlang:is_record(T) of
        true -> [records:get(F, T) || F <- records:get_field_names(T)];
        false -> []
    end.
-else.
is_native_record(_) -> false.

record_values(_) -> [].
-endif.

%% Bytes that change between runs of this generator: local funs (Uniq
%% follows the code), this node's pids, ports and refs, and maps with keys
%% other than integers (the key order follows atom indexes and hash salts,
%% which differ per VM run).
volatile(Term) ->
    any_sub(fun(T) ->
                    (is_function(T) andalso
                     erlang:fun_info(T, type) =:= {type, local})
                        orelse ((is_pid(T) orelse is_port(T) orelse is_reference(T))
                                andalso node(T) =:= node())
                        orelse (is_map(T) andalso map_size(T) > 1
                                andalso not lists:all(fun is_integer/1, maps:keys(T)))
            end, Term).

any_sub(P, T) ->
    P(T) orelse
        if
            is_list(T) -> any_list(P, T);
            is_tuple(T) -> any_list(P, tuple_to_list(T));
            is_map(T) -> any_list(P, maps:keys(T) ++ maps:values(T));
            is_function(T) -> {env, Env} = erlang:fun_info(T, env), any_list(P, Env);
            true -> any_list(P, record_values(T))
        end.

any_list(P, [H | T]) -> any_sub(P, H) orelse any_list(P, T);
any_list(_, []) -> false;
any_list(P, Tail) -> any_sub(P, Tail).

check_unique(Names) ->
    case Names -- lists:usort(Names) of
        [] -> ok;
        Dups -> error({duplicate_fixture_names, Dups})
    end.

%% The ??Expr text has a space between every token; re-print it with erl_pp
%% and fold it onto one line. Fall back to the raw text if it does not parse.
pretty(Source) ->
    try
        {ok, Tokens, _} = erl_scan:string(Source),
        {ok, Exprs} = erl_parse:parse_exprs(Tokens ++ [{dot, 1}]),
        Text = erl_pp:exprs(Exprs),
        re:replace(Text, "\\n\\s*", " ", [global, unicode, {return, list}])
    catch
        _:_ -> Source
    end.

fixtures() ->
    integers() ++ floats() ++ atoms() ++ strings() ++ lists() ++ tuples()
        ++ maps() ++ binaries() ++ compressed() ++ node_containers()
        ++ funs() ++ records() ++ local().

integers() ->
    [?F(int_0, stable, 0),
     ?F(int_255, stable, 255),
     ?F(int_256, stable, 256),
     ?F(int_neg_1, stable, -1),
     ?F(int_2p31_minus_1, stable, (1 bsl 31) - 1),
     ?F(int_neg_2p31, stable, -(1 bsl 31)),
     ?F(int_neg_2p31_minus_1, stable, -(1 bsl 31) - 1),
     ?F(int_2p31, stable, 1 bsl 31),
     ?F(int_2p32_minus_1, stable, (1 bsl 32) - 1),
     ?F(int_2p32, stable, 1 bsl 32),
     ?F(int_2p64, stable, 1 bsl 64),
     ?F(int_neg_2p64, stable, -(1 bsl 64)),
     %% 2^2039 needs 255 bytes (SMALL_BIG_EXT), 2^2040 needs 256 (LARGE_BIG_EXT).
     ?F(int_2p2039, stable, 1 bsl 2039),
     ?F(int_2p2040_minus_1, stable, (1 bsl 2040) - 1),
     ?F(int_2p2040, stable, 1 bsl 2040)].

floats() ->
    [?F(float_0, stable, 0.0),
     ?F(float_neg_0, stable, -0.0),
     ?F(float_1_5, stable, 1.5),
     ?F(float_1e308, stable, 1.0e308),
     ?F(float_1_5_minor_0, stable, 1.5, [{minor_version, 0}])].

%% Every atom twice: default encoding (UTF-8 tags) and {minor_version, 1}
%% (Latin-1 tags where the text allows it).
atoms() ->
    Atoms =
        [?F(atom_empty, stable, ''),
         ?F(atom_ascii, stable, hello),
         ?F(atom_latin1, stable, list_to_atom([16#E9])),
         ?F(atom_utf8, stable, list_to_atom([16#43F, 16#440, 16#438])),
         ?F(atom_255_ascii, stable, list_to_atom(lists:duplicate(255, $a))),
         ?F(atom_255_4byte, stable, list_to_atom(lists:duplicate(255, 16#1F600)))],
    Atoms ++ [{list_to_atom(atom_to_list(N) ++ "_minor_1"), S, Src, T,
               [{minor_version, 1}]}
              || {N, S, Src, T, []} <- Atoms].

strings() ->
    [?F(str_empty, stable, ""),
     ?F(str_abc, stable, "abc"),
     ?F(str_latin1, stable, [16#E9]),
     ?F(str_65535, stable, lists:duplicate(65535, $a)),
     ?F(str_65536, stable, lists:duplicate(65536, $a)),
     ?F(str_wide, stable, [$a, 256, $b])].

lists() ->
    [?F(list_proper, stable, [a, 1, {b}]),
     ?F(list_nested, stable, [[a, [b]], [], [c]]),
     ?F(list_improper, stable, [1 | 2])].

tuples() ->
    [?F(tuple_0, stable, {}),
     ?F(tuple_255, stable, list_to_tuple(lists:seq(1, 255))),
     ?F(tuple_256, stable, list_to_tuple(lists:seq(1, 256)))].

%% 32 keys is the largest flatmap; 33 keys is a hash map, whose encoding order
%% follows OTP's internal hash.
maps() ->
    [?F(map_0, stable, #{}),
     ?F(map_32, stable, maps:from_list([{K, K} || K <- lists:seq(1, 32)])),
     ?F(map_33, stable, maps:from_list([{K, K} || K <- lists:seq(1, 33)])),
     ?F(map_list_key, stable, #{[a, b] => 1}),
     ?F(map_map_key, stable, #{#{a => 1} => 2}),
     %% Keys that are different in Erlang and equal in Python (TERM-23).
     ?F(map_int_float_key, stable, #{1 => a, 1.0 => b}),
     ?F(map_true_int_key, stable, #{true => x, 1 => y}),
     ?F(map_tuple_int_float_key, stable, #{{1} => a, {1.0} => b}),
     ?F(map_zero_keys, stable, #{0.0 => a, -0.0 => b}),
     ?F(map_atom_string_key, stable, #{abc => a, "abc" => b})].

binaries() ->
    [?F(bin_empty, stable, <<>>),
     ?F(bin_1_2_3, stable, <<1, 2, 3>>),
     ?F(bits_1_1, stable, <<1:1>>),
     ?F(bits_5_7, stable, <<5:7>>),
     ?F(bits_1_2_3_4, stable, <<1, 2, 3:4>>)].

compressed() ->
    [?F(compressed_list, stable, lists:duplicate(200, {hello, <<"world">>}),
        [compressed])].

%% Pids, ports and refs of node 'fix@host' with fixed ids, built from
%% hand-written bytes and re-encoded by OTP.
node_containers() ->
    [?F(pid_small, stable, pid(1, 2, 3)),
     ?F(pid_max, stable, pid(16#FFFFFFFF, 16#FFFFFFFF, 16#FFFFFFFF)),
     ?F(port_2p28_minus_1, stable, new_port((1 bsl 28) - 1, 1)),
     ?F(port_2p28, stable, new_port(1 bsl 28, 1)),
     ?F(port_2p64_minus_1, stable, v4_port((1 bsl 64) - 1, 16#FFFFFFFF)),
     ?F(ref_1_word, stable, ref([1], 1)),
     ?F(ref_3_words, stable, ref([1, 2, 3], 1)),
     ?F(ref_5_words, stable, ref([1, 2, 3, 4, 5], 1)),
     ?F(ref_max_creation, stable,
        ref([16#FFFFFFFF, 16#FFFFFFFF, 16#FFFFFFFF], 16#FFFFFFFF))].

%% Local funs carry this module's Uniq, which changes with the code.
funs() ->
    [?F(fun_export, stable, fun lists:map/2),
     ?F(fun_local, volatile, fun(X) -> X + 1 end),
     ?F(fun_closure, volatile, closure(1, two))].

-if(?OTP_RELEASE >= 29).
records() ->
    [?F(record_exported, stable, #fix_exported{b = [1, 2]}),
     ?F(record_local, stable, #fix_local{x = {1, 2}}),
     ?F(record_empty, stable, #fix_empty{}),
     ?F(record_nested, stable, #fix_exported{a = #fix_local{x = #fix_empty{}}})].
-else.
records() ->
    [].
-endif.

%% term_to_binary(T, [local]) (OTP 26+): LOCAL_EXT, which only the node
%% that wrote it can decode; its bytes depend on the node.
-if(?OTP_RELEASE >= 26).
local() ->
    [?F(local_ext, volatile, {a, 1}, [local])].
-else.
local() ->
    [].
-endif.

%% A fun with two free variables (A and B).
closure(A, B) ->
    fun(X) -> {A, B, X} end.

node_atom() ->
    Name = atom_to_binary(?FIX_NODE, utf8),
    <<119, (byte_size(Name)):8, Name/binary>>.

%% NEW_PID_EXT
pid(Id, Serial, Creation) ->
    binary_to_term(<<131, 88, (node_atom())/binary,
                     Id:32, Serial:32, Creation:32>>).

%% NEW_PORT_EXT (32-bit id)
new_port(Id, Creation) ->
    binary_to_term(<<131, 89, (node_atom())/binary, Id:32, Creation:32>>).

%% V4_PORT_EXT (64-bit id)
v4_port(Id, Creation) ->
    binary_to_term(<<131, 120, (node_atom())/binary, Id:64, Creation:32>>).

%% NEWER_REFERENCE_EXT
ref(Words, Creation) ->
    Ids = << <<W:32>> || W <- Words >>,
    binary_to_term(<<131, 90, (length(Words)):16, (node_atom())/binary,
                     Creation:32, Ids/binary>>).
