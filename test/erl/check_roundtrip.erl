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

%% OTP judges what our codecs encode (plan step TERM-04): for every
%% <OursDir>/<name>.etf, the term it decodes to must be exactly (=:=) the
%% term that OTP's own <FixtureDir>/<name>.etf decodes to.
%%
%%   erl -noshell -pa <dir with check_roundtrip.beam> \
%%       -run check_roundtrip main FixtureDir1 OursDir1 [FixtureDir2 OursDir2 ...]
%%
%% Several (fixture dir, ours dir) pairs are checked by one VM start. Output,
%% one line each, tab-separated:
%%   mismatch     <OursDir>  <name>  <reason>
%%   undecodable  <OursDir>  <name>   (this release cannot decode the fixture
%%                                     itself, e.g. a native record before
%%                                     OTP 29: nothing to compare with)
%%   checked      <OursDir>  <count>
%% The VM exits with status 0 when every file matched, 1 otherwise.

-module(check_roundtrip).

-export([main/1]).

main(Args) ->
    Pairs = pairs(Args),
    Bad = lists:sum([check_dir(Fix, Ours) || {Fix, Ours} <- Pairs]),
    halt(case Bad of 0 -> 0; _ -> 1 end).

pairs([Fix, Ours | Rest]) -> [{Fix, Ours} | pairs(Rest)];
pairs([]) -> [];
pairs(Odd) -> error({unpaired_directory, Odd}).

%% Returns the number of mismatches in one directory.
check_dir(FixDir, OursDir) ->
    Files = lists:sort(filelib:wildcard("*.etf", OursDir)),
    Bad = length([bad || F <- Files, check_file(FixDir, OursDir, F) =/= ok]),
    io:format("checked\t~ts\t~b~n", [OursDir, length(Files)]),
    Bad.

check_file(FixDir, OursDir, File) ->
    Name = filename:rootname(File),
    Result =
        case {file:read_file(filename:join(FixDir, File)),
              file:read_file(filename:join(OursDir, File))} of
            {{ok, Theirs}, {ok, Ours}} -> compare(Theirs, Ours);
            {{error, Reason}, _} -> {no_fixture, Reason};
            {_, {error, Reason}} -> {unreadable, Reason}
        end,
    case Result of
        ok ->
            ok;
        fixture_undecodable ->
            io:format("undecodable\t~ts\t~ts~n", [OursDir, Name]),
            ok;
        _ ->
            io:format("mismatch\t~ts\t~ts\t~0P~n", [OursDir, Name, Result, 12]),
            Result
    end.

compare(Theirs, Ours) ->
    try binary_to_term(Theirs) of
        Expected -> compare_ours(Expected, Ours)
    catch
        error:badarg -> fixture_undecodable
    end.

compare_ours(Expected, Ours) ->
    try binary_to_term(Ours) of
        Decoded when Decoded =:= Expected -> ok;
        Other -> {different, Other}
    catch
        error:badarg -> not_decodable
    end.
