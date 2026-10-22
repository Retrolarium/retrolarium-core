# Retrolarium's default PowerShell format (Invoke-Formatter); a repository's
# own PSScriptAnalyzerSettings.psd1 replaces it.
@{
    IncludeRules = @(
        'PSPlaceOpenBrace',
        'PSPlaceCloseBrace',
        'PSUseConsistentWhitespace',
        'PSAlignAssignmentStatement',
        'PSUseCorrectCasing'
    )
    Rules = @{
        PSPlaceOpenBrace = @{ Enable = $true; OnSameLine = $true; NewLineAfter = $true; IgnoreOneLineBlock = $true }
        PSPlaceCloseBrace = @{ Enable = $true; NewLineAfter = $false; IgnoreOneLineBlock = $true; NoEmptyLineBefore = $false }
        # Indentation stays as written: the rule moves backtick continuations to column 0
        PSUseConsistentWhitespace = @{ Enable = $true; CheckOpenBrace = $true; CheckOpenParen = $true; CheckOperator = $true; CheckSeparator = $true; CheckPipe = $true }
        PSAlignAssignmentStatement = @{ Enable = $false }
        PSUseCorrectCasing = @{ Enable = $true }
    }
}
