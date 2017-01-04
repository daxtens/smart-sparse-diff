#!/usr/bin/python3
import sys
from typing import Dict, List, Tuple, Any

verbose = False
def vprint(*args, **kwargs):
    if verbose:
        print(*args, **kwargs)

def deinterleave_by_file(log: str) -> Dict[str, List[List[str]]]:
    # zeroeth pass: things get interleaved with multiprocess compilation
    # so deinterleave it first
    lines_by_file = {} # type: Dict[str, List[List[str]]]
    for line in log.split("\n"):
        parts = line.split(":")

        filename = parts[0]

        if filename not in lines_by_file:
            lines_by_file[filename] = []

        lines_by_file[filename] += [parts]

    return lines_by_file

def concat_multi_line_warnings(split_lines: List[List[str]]) -> List[List[str]]:
    # first pass: concatenate irritating things like:
    #drivers/scsi/lpfc/lpfc_scsi.c:5606:30: warning: incorrect type in assignment (different base types)
    #drivers/scsi/lpfc/lpfc_scsi.c:5606:30:    expected int [signed] memory_flags
    #drivers/scsi/lpfc/lpfc_scsi.c:5606:30:    got restricted gfp_t
    lines = [] # type: List[List[str]]
    last_column = ""
    last_line = ""
    for parts in split_lines:

        if len(parts) < 4:
            # this doesn't have enough parts to be a 'real' line. warn and proceed.
            #print('Found odd line "%s", ignoring.' % line)
            lines += [parts]
            continue

        (linenum, columnnum) = parts[1:3]
        final_mandatory_part = parts[3].strip()
        final_parts = ":".join(parts[3:]).strip()

        #vprint(line)
        if (linenum != last_line) or \
           (last_column != columnnum):
            # this is a different line and column, it cannot be a concatenation
            lines += [parts]
            #vprint("different f/l/c")
        elif (final_mandatory_part == "warning") or \
             (final_mandatory_part == "error"):
            # this has an explicit type: it is a new message
            lines += [parts]
            #vprint("explicit type")
        else:
            # looks like this is a continuation
            last_line_parts = lines[-1]
            last_line_parts[-1] += " " + final_parts
            lines[-1] = last_line_parts
            #vprint("concat: new last: " + str(lines[-1]))

        last_line = linenum
        last_column = columnnum

    return lines

def parse_log_by_file(log: str) -> Dict[str, List[List[str]]]:

    lines_by_file = deinterleave_by_file(log)

    concat_lines_by_file = {}
    for filename in lines_by_file:
        concat_lines_by_file[filename] = concat_multi_line_warnings(lines_by_file[filename])

    return concat_lines_by_file

def smart_filter(a: List[Any],
                 b: List[Any]) -> List[Any]:
    res = [] # type: List[str]
    # two reasons we'd want to keep a line:
    # it does not appear in the other at all
    # it appears an unequal number of times (think headers)
    #  (to manage this in the report, only include it where it appears
    #   more times)
    for l in a:
        if l not in b:
            res += [l]
        else:
            if len([ll for ll in a if ll == l]) > \
               len([ll for ll in b if ll == l]):
                
                # save only once
                if l not in res:
                    res += [l]
    return res

def remove_exact_matching_lines(old_lines: List[List[str]],
                                new_lines: List[List[str]]) \
                                -> Tuple[List[List[str]], List[List[str]]]:

    new_old = smart_filter(old_lines, new_lines)
    new_new = smart_filter(new_lines, old_lines)

    if new_old == []:
        new_old = None

    if new_new == []:
        new_new = None
    
    return (new_old, new_new)

def remove_lines_diff_by_only_line_no(old_lines, new_lines):

    # drop weird short lines
    safe_old_lines = []
    for parts in old_lines:
        if len(parts) < 4:
            # this doesn't have enough parts to be a 'real' line. warn and proceed.
            print('Found odd line "%s" in old file, ignoring.' % line)
        else:
            safe_old_lines += [parts]
    safe_new_lines = []
    for parts in new_lines:
        if len(parts) < 4:
            # this doesn't have enough parts to be a 'real' line. warn and proceed.
            print('Found odd line "%s" in new file, ignoring.' % line)
        else:
            safe_new_lines += [parts]
            
    old_wo_line = [":".join([l[0]] + l[2:]) for l in safe_old_lines]
    new_wo_line = [":".join([l[0]] + l[2:]) for l in safe_new_lines]

    new_old = smart_filter(old_wo_line, new_wo_line)
    new_new = smart_filter(new_wo_line, old_wo_line)

    old_parts = [l.split(':') for l in new_old]
    new_parts = [l.split(':') for l in new_new]

    old_parts = [[l[0], 'XX'] + l[1:] for l in old_parts]
    new_parts = [[l[0], 'XX'] + l[1:] for l in new_parts]

    if old_parts == []:
        old_parts = None
    if new_parts == []:
        new_parts = None

    return (old_parts, new_parts)

def format_one_warning(parts: List[str]) -> str:
    return ":".join(parts)


def smart_diff(old_log, new_log):
    old_by_file = parse_log_by_file(old_log)
    new_by_file = parse_log_by_file(new_log)

    # todo - this structure is helpful for progressive development and
    # debugging, but is not very efficient

    # we now have 2x { filename: [list of warnings] }
    # go to 1x { filename: (old warnings, new warnings) }
    combined_warnings = {}
    for filename in set(old_by_file.keys()) | set(new_by_file.keys()):
        olds = None
        if filename in old_by_file:
            olds = old_by_file[filename]

        news = None
        if filename in new_by_file:
            news = new_by_file[filename]

        combined_warnings[filename] = (olds, news)

    only_new = {}
    only_old = {}
    # lets winnow out our lists a bit
    changed = {}
    for filename in combined_warnings:
        (olds, news) = combined_warnings[filename]

        if news and not olds:
            only_new[filename] = (olds, news)
        elif olds and not news:
            only_old[filename] = (olds, news)
        elif not olds and not news:
            print("Something weird going on with: " + filename)
        else:
            changed[filename] = (olds, news)

    vprint("After parsing:")
    vprint("Only new warnings: " + str(len(only_new.keys())))
    vprint("Only old warnings: " + str(len(only_old.keys())))
    vprint("Changed: " + str(len(changed.keys())))

        
    # remove entire duplicated files
    changed_1 = {}
    for filename in changed:
        (olds, news) = changed[filename]
        if olds == news:
            vprint("exact complete match drops: " + filename)
        else:
            changed_1[filename] = (olds, news)

    vprint("After removing exact file matches:")
    vprint("Only new warnings: " + str(len(only_new.keys())))
    vprint("Only old warnings: " + str(len(only_old.keys())))
    vprint("Changed: " + str(len(changed_1.keys())))

    # now, lets just try removing exact matching lines
    changed_2 = {}
    for filename in changed_1:
        (olds, news) = changed_1[filename]
        (olds, news) = remove_exact_matching_lines(olds, news)
        if not olds and not news:
            vprint("remove_exact_matching_lines completely matched: " + filename)
        elif olds and not news:
            only_old[filename] = (olds, news)
        elif not olds and news:
            only_new[filename] = (olds, news)
        else:
            changed_2[filename] = (olds, news)

    vprint("After removing exact line matches:")
    vprint("Only new warnings: " + str(len(only_new.keys())))
    vprint("Only old warnings: " + str(len(only_old.keys())))
    vprint("Changed: " + str(len(changed_2.keys())))

    # now, lets just try removing lines w/ matching column, diff line
    changed_3 = {}
    for filename in changed_2:
        (olds, news) = remove_lines_diff_by_only_line_no(*changed_2[filename])
        if olds and news:
            changed_3[filename] = (olds, news)
        elif olds and not news:
            only_old[filename] = (olds, news)
        elif not olds and news:
            only_new[filename] = (olds, news)
        else:
            vprint("diff by only line no removed: " + filename)

    vprint("After removing warnings differing in line number only (same column, message):")
    vprint("Only new warnings: " + str(len(only_new.keys())))
    vprint("Only old warnings: " + str(len(only_old.keys())))
    vprint("Changed: " + str(len(changed_3.keys())))

    #fn = list(changed_3.keys())[0]
    #ch = changed_3[fn]

    return (only_old, only_new, changed_3)

    
def usage(exec_name):
    print("Usage: %s <oldfile> <newfile>" % exec_name)
    print("    attempt a smart diff between sparse logs in oldfile and newfile")
    exit(1)
    
if __name__ == '__main__':
    if len(sys.argv) != 3:
        usage(sys.argv[0])

    try:
        with open(sys.argv[1], 'r') as old_file:
            old_log = old_file.read()
    except:
        print("Error reading old log file %s" % old_file)
        exit(1)

    try:
        with open(sys.argv[2], 'r') as new_file:
            new_log = new_file.read()
    except:
        print("Error reading new log file %s" % new_file)
        exit(1)

    (only_old, only_new, changed) = smart_diff(old_log, new_log)

    removed = [only_old[o][0] for o in only_old] + [changed[c][0] for c in changed]
    added = [only_new[n][1] for n in only_new] + [changed[c][1] for c in changed]

    lines = [] # type: List[str]
    for sublist in removed:
        for w in sublist:
            lines += ['-' + format_one_warning(w)]
    for sublist in added:
        for w in sublist:
            lines += ['+' + format_one_warning(w)]

    lines.sort(key=lambda x: x[1:])
    for l in lines:
        print(l)

