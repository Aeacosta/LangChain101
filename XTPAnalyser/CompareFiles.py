import difflib

# Read both text files into memory as lists of lines
with open(r"Programas/Commercial_Standard.xtp", 'r', encoding='utf-8') as f1, open(r"Programas/Production_Standard.xtp", 'r', encoding='utf-8') as f2:
    file1_lines = f1.readlines()
    file2_lines = f2.readlines()

# Compute the unified diff sequence
delta = difflib.unified_diff(
    file1_lines, 
    file2_lines, 
    fromfile=r"Programas/Commercial_Standard.xtp", 
    tofile=r"Programas/Production_Standard.xtp",
    lineterm=''
)

# Print the resulting modifications to terminal
for line in delta:
    print(line)
