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
%%   erlc -o test/erl test/erl/gen_fixtures.erl
%%   erl -noshell -pa test/erl -run gen_fixtures main test/fixtures -s init stop
%%
%% For each fixture, writes <OutDir>/<name>.etf (term_to_binary(Term, Opts))
%% and one line in <OutDir>/MANIFEST.tsv with the columns
%%   name, otp_release, stability, source, options
%% `source` is the Erlang expression that built the term, re-printed by
%% erl_pp on one line (integers appear in decimal); helper calls such as
%% pid/3 refer to the functions at the end of this module. `stability` is
%% `stable` when the bytes depend only on the OTP release, or `volatile`
%% when they also depend on this module's compiled code (fun Uniq values).
%% Old *.etf files in <OutDir> are removed first, so the directory always
%% matches the manifest.

-module(gen_fixtures).

-export([main/1]).

%% {Name, Stability, Source text, Term, term_to_binary options}; ??Expr keeps
%% the expression text so the manifest shows how each term was built.
-define(F(Name, Stability, Expr), {Name, Stability, ??Expr, Expr, []}).
-define(F(Name, Stability, Expr, Opts), {Name, Stability, ??Expr, Expr, Opts}).

%% Node name used for every hand-built pid, port and reference.
-define(FIX_NODE, 'fix@host').

-if(?OTP_RELEASE >= 29).
%% Native records (EEP-79, OTP 29): one exported, one module-local.
-export_record([fix_exported]).
-record #fix_exported{a = 1, b = two}.
-record #fix_local{x, y = []}.
-endif.

%% Entry point for `erl -run gen_fixtures main OutDir`.
main([OutDir]) ->
    ok = filelib:ensure_dir(filename:join(OutDir, "MANIFEST.tsv")),
    Old = filelib:wildcard(filename:join(OutDir, "*.etf")),
    lists:foreach(fun(F) -> ok = file:delete(F) end, Old),
    Release = erlang:system_info(otp_release),
    Fixtures = fixtures(),
    ok = check_unique([Name || {Name, _, _, _, _} <- Fixtures]),
    Lines = [write_fixture(OutDir, Release, F) || F <- Fixtures],
    Header = "name\totp_release\tstability\tsource\toptions\n",
    Manifest = unicode:characters_to_binary([Header | Lines]),
    ok = file:write_file(filename:join(OutDir, "MANIFEST.tsv"), Manifest),
    io:format("wrote ~b fixtures to ~ts~n", [length(Fixtures), OutDir]).

write_fixture(OutDir, Release, {Name, Stability, Source, Term, Opts}) ->
    Bin = term_to_binary(Term, Opts),
    %% A fixture that does not survive OTP's own decoder is a generator bug.
    Term = binary_to_term(Bin),
    File = filename:join(OutDir, atom_to_list(Name) ++ ".etf"),
    ok = file:write_file(File, Bin),
    io_lib:format("~ts\t~ts\t~ts\t~ts\t~0p~n",
                  [Name, Release, Stability, pretty(Source), Opts]).

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
        ++ funs() ++ records().

integers() ->
    [?F(int_0, stable, 0),
     ?F(int_255, stable, 255),
     ?F(int_256, stable, 256),
     ?F(int_neg_1, stable, -1),
     ?F(int_2p31_minus_1, stable, (1 bsl 31) - 1),
     ?F(int_neg_2p31, stable, -(1 bsl 31)),
     ?F(int_2p31, stable, 1 bsl 31),
     ?F(int_2p32_minus_1, stable, (1 bsl 32) - 1),
     ?F(int_2p32, stable, 1 bsl 32),
     ?F(int_2p64, stable, 1 bsl 64),
     ?F(int_neg_2p64, stable, -(1 bsl 64)),
     %% 2^2039 needs 255 bytes (SMALL_BIG_EXT), 2^2040 needs 256 (LARGE_BIG_EXT).
     ?F(int_2p2039, stable, 1 bsl 2039),
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
     ?F(map_map_key, stable, #{#{a => 1} => 2})].

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
     ?F(record_local, stable, #fix_local{x = {1, 2}})].
-else.
records() ->
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
