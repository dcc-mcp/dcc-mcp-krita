from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.get_active_document", "Active Krita document inspected.", "document")

if __name__ == "__main__":
    run_main(main)
