# Subsystem SUMMARY.md Template

Use this exact structure when generating a subsystem summary.
Sections marked `<!-- optional -->` should be omitted if not applicable.
Target length: 30-80 lines.

Key differences from the module template:
- No "Module Relationships" section (subsystems don't have Build.cs deps)
- Adds "Internal Architecture" section for intra-subsystem data flow
- Shorter than module summaries (30-80 lines vs 60-150)

```markdown
# Subsystem: {ModuleName}/{SubsystemName}

## Purpose
{One sentence: what this subsystem does within the parent module}

## Key Concepts
- **{ClassName}**: {What it represents, one line}
<!-- List 3-8 most important classes/structs. -->

## Entry Points
- `{File.cpp}` -> `{Class::Function()}`: {When this is called}
<!-- 2-4 primary entry points. -->

## Internal Architecture
- {How the pieces connect within this subsystem}
<!-- 2-5 bullets describing the internal flow/pipeline. -->

## Modification Guide
- **{Task}**: {Which files, what pattern}
<!-- 2-4 modification scenarios specific to this subsystem. -->

<!-- optional -->
## Shader Bindings
- `{Shader.usf}` <-> `{Cpp.cpp}`: {Data flow}

<!-- optional -->
## Console Variables
- `{CvarName}`: {What it controls} (`{File.cpp}`)

## Files
{N} source files in {source_dirs}.

## Last Updated
{YYYY-MM-DD} - {Brief note}
```

## Quality Checklist

Before writing a subsystem summary, verify:
- [ ] Purpose is one sentence, scoped to the subsystem (not the whole module)
- [ ] Key Concepts lists actual classes from the subsystem's headers
- [ ] Entry Points have real file paths (verified via Glob/Read)
- [ ] Internal Architecture describes how this subsystem's pieces connect
- [ ] Modification Guide is actionable and subsystem-specific
- [ ] Total length is 30-80 lines (trim if longer)
- [ ] No fabricated class names or file paths
