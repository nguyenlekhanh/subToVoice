import re

with open(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all method definitions
methods = re.findall(r'^\s{4}def _(\w+)\(', content, re.MULTILINE)
print('=== DEFINED METHODS ===')
for m in sorted(set(methods)):
    print(f'  _ {m}')

# Find all self.method references
refs = re.findall(r'self\._(\w+)\(', content)
print('\n=== METHOD CALLS (self._xxx) ===')
for r in sorted(set(refs)):
    print(f'  self._{r}()')

# Find all bind calls
binds = re.findall(r'\.bind\([^,]+,\s*self\._(\w+)', content)
print('\n=== BIND CALLBACKS ===')
for b in sorted(set(binds)):
    print(f'  bind -> _{b}')

# Find all root.after calls
afters = re.findall(r'root\.after\([^,]+,\s*self\._(\w+)', content)
print('\n=== ROOT.AFTER CALLBACKS ===')
for a in sorted(set(afters)):
    print(f'  root.after -> _{a}')

# Find all command= references
cmds = re.findall(r'command=self\._(\w+)', content)
print('\n=== COMMAND CALLBACKS ===')
for c in sorted(set(cmds)):
    print(f'  command= -> _{c}')

# Find all thread targets
threads = re.findall(r'target=self\._(\w+)', content)
print('\n=== THREAD TARGETS ===')
for t in sorted(set(threads)):
    print(f'  thread -> _{t}')

# Find all thread starts
thread_starts = re.findall(r'_(\w+)\.start\(\)', content)
print('\n=== THREAD STARTS ===')
for t in sorted(set(thread_starts)):
    print(f'  .start() -> _{t}')

# Find all root.after calls with lambdas
after_lambdas = re.findall(r'root\.after\([^,]+,\s*lambda[^:]+: self\._(\w+)', content)
print('\n=== ROOT.AFTER LAMBDAS ===')
for a in sorted(set(after_lambdas)):
    print(f'  root.after lambda -> _{a}')

# Find all tag_bind
tag_binds = re.findall(r'tag_bind\([^,]+,\s*[^,]+,\s*lambda[^:]+: self\._(\w+)', content)
print('\n=== TAG_BIND CALLBACKS ===')
for t in sorted(set(tag_binds)):
    print(f'  tag_bind -> _{t}')

# Find all command= references
cmds = re.findall(r'command=self\._(\w+)', content)
print('\n=== COMMAND= ===')
for c in sorted(set(cmds)):
    print(f'  command= -> _{c}')