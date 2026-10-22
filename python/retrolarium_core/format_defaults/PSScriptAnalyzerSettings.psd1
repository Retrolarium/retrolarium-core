# Retrolarium's default PowerShell format (Invoke-Formatter); a repository's
# own PSScriptAnalyzerSettings.psd1 replaces it.
@{
    IncludeRules = @(
        'PSPlaceOpenBrace',
        'PSPlaceCloseBrace',
        'PSUseConsistentIndentation',
        'PSUseConsistentWhitespace',
        'PSAlignAssignmentStatement',
        'PSUseCorrectCasing'
    )
    Rules = @{
        PSPlaceOpenBrace = @{ Enable = $true; OnSameLine = $true; NewLineAfter = $true; IgnoreOneLineBlock = $true }
        PSPlaceCloseBrace = @{ Enable = $true; NewLineAfter = $false; IgnoreOneLineBlock = $true; NoEmptyLineBefore = $false }
        PSUseConsistentIndentation = @{ Enable = $true; IndentationSize = 4; Kind = 'space'; PipelineIndentation = 'IncreaseIndentationForFirstPipeline' }
        PSUseConsistentWhitespace = @{ Enable = $true; CheckOpenBrace = $true; CheckOpenParen = $true; CheckOperator = $true; CheckSeparator = $true; CheckPipe = $true }
        PSAlignAssignmentStatement = @{ Enable = $false }
        PSUseCorrectCasing = @{ Enable = $true }
    }
}
