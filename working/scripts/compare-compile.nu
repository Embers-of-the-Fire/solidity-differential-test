#!/usr/bin/env nu

def require-tool [tool: string] {
    if ((which $tool | length) == 0) {
        print -e $"($tool) is not available. Enter the shell with `nix develop`."
        exit 1
    }
}

def write-result [result: record, out_dir: path, prefix: string] {
    $result.stdout | save -f ($out_dir | path join $"($prefix).stdout")
    $result.stderr | save -f ($out_dir | path join $"($prefix).stderr")

    if $result.exit_code == 0 {
        "success" | save -f ($out_dir | path join $"($prefix).status")
    } else {
        "failure" | save -f ($out_dir | path join $"($prefix).status")
    }
}

def show-diff [left: path, right: path] {
    let result = (^diff -u $left $right | complete)

    if ($result.stdout | str length) > 0 {
        print ($result.stdout | str trim --right)
    }

    if ($result.stderr | str length) > 0 {
        print -e ($result.stderr | str trim --right)
    }

    $result.exit_code
}

let root_result = (^git rev-parse --show-toplevel | complete)
let root_dir = if $root_result.exit_code == 0 {
    $root_result.stdout | str trim
} else {
    pwd | get path
}

let cases_dir = ($root_dir | path join "working" "cases")
let out_dir = ($root_dir | path join "working" "out")

mkdir $out_dir

require-tool solc
require-tool solang

mut status = 0
let sources = (glob ($cases_dir | path join "*.sol") | sort)

for source in $sources {
    let base = ($source | path parse | get stem)
    let case_out = ($out_dir | path join $base)

    mkdir $case_out

    print $"==> ($base)"

    # Capture both success output and compiler diagnostics for solc.
    let solc_result = (^solc --abi --bin $source | complete)
    write-result $solc_result $case_out "solc"

    # Targeting Solana keeps solang in a non-EVM mode where behavioral drift is common.
    # The goal here is not equivalence of artifacts, but quick visibility into parser,
    # semantic, and code generation differences between the compilers.
    let solang_result = (
        ^solang compile $source --target solana --output ($case_out | path join "solang-artifacts") | complete
    )
    write-result $solang_result $case_out "solang"

    if (show-diff ($case_out | path join "solc.status") ($case_out | path join "solang.status")) != 0 {
        $status = 1
    }

    if (show-diff ($case_out | path join "solc.stderr") ($case_out | path join "solang.stderr")) != 0 {
        $status = 1
    }
}

exit $status
