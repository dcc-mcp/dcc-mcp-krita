from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.save_document", "Krita document saved.")

if __name__ == "__main__":
    run_main(main)
