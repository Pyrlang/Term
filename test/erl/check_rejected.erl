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

%% OTP judges the malformed inputs of test_bad_terms.py (plan step TERM-05):
%% every input that our decoders must reject, binary_to_term/1 must reject
%% too. The input file is a sequence of records <<Len:32, Bytes:Len/binary>>.
%%
%%   erl -noshell -pa <dir with check_rejected.beam> \
%%       -run check_rejected main InputFile
%%
%% Output, one line each, tab-separated:
%%   accepted  <record index, from 0>  <decoded term, abbreviated>
%%   checked   <record count>
%% The VM exits with status 0 when every record was rejected, 1 otherwise.

-module(check_rejected).

-export([main/1]).

main([File]) ->
    {ok, Bin} = file:read_file(File),
    {Count, Accepted} = check(Bin, 0, 0),
    io:format("checked\t~b~n", [Count]),
    halt(case Accepted of 0 -> 0; _ -> 1 end).

check(<<Len:32, Bytes:Len/binary, Rest/binary>>, Index, Accepted) ->
    try binary_to_term(Bytes) of
        Term ->
            io:format("accepted\t~b\t~0P~n", [Index, Term, 8]),
            check(Rest, Index + 1, Accepted + 1)
    catch
        error:badarg -> check(Rest, Index + 1, Accepted)
    end;
check(<<>>, Count, Accepted) ->
    {Count, Accepted}.
