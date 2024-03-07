from collections import OrderedDict


def pformat_dict(data, separator='  '):
    column_widths = OrderedDict([(k, max([len(k)] +
                                         [len(str(v)) for v in values]))
                                 for k, values in data.items()])

    header = separator.join([('{:>%ds}' % (column_width)).format(value)
                             for value, column_width in
                             zip(list(data.keys()), list(column_widths.values()))])
    hbar = separator.join(['-' * column_width
                           for column_width in column_widths.values()])
    rows = [separator.join([('{:>%ds}' % (column_width)).format(value)
                            for value, column_width in
                            zip(row, list(column_widths.values()))])
            for row in zip(*list(data.values()))]

    return '\n'.join([header, hbar] + rows)
