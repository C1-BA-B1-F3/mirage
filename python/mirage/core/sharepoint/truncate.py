from mirage.core.msgraph.drive import make_truncate
from mirage.core.sharepoint.read import read_bytes
from mirage.core.sharepoint.write import write_bytes

truncate = make_truncate(read_bytes, write_bytes)
