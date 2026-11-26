/* SPDX-License-Identifier: GPL-2.0-or-later */

#include "GHOST_IOSFarm.hh"

#import <UIKit/UIKit.h>

#include <cstring>
#include <vector>

int GHOST_IOS_farmLaunch(int argc, const char **argv, int (*launch)(int, const char **))
{
  NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory
                                                          inDomains:NSUserDomainMask].firstObject;
  NSURL *config = [documents URLByAppendingPathComponent:@"farm.json"];
  bool requested = config && [NSFileManager.defaultManager fileExistsAtPath:config.path];
  /* Blender consumes its own switches. Keep worker options in sys.argv after its
   * separator, including when devicectl has already stripped the separator. */
  std::vector<const char *> blender_args = {argv[0], "--addons", "farm_worker"};
  std::vector<const char *> script_args;
  bool after_separator = false;
  for (int i = 1; i < argc; i++) {
    const char *arg = argv[i];
    if (!after_separator && strcmp(arg, "--") == 0) {
      after_separator = true;
      continue;
    }
    int count = strcmp(arg, "--farm-worker") == 0 ? 2 : strcmp(arg, "--mcp-port") == 0 ? 1 : 0;
    if (count) {
      requested = true;
      script_args.push_back(arg);
      while (count-- && i + 1 < argc && strncmp(argv[i + 1], "--", 2) != 0) {
        script_args.push_back(argv[++i]);
      }
    }
    else {
      (after_separator ? script_args : blender_args).push_back(arg);
    }
  }
  if (!requested) {
    return launch(argc, argv);
  }
  /* Keep the argv storage alive for the lifetime of the process. */
  static std::vector<const char *> launch_args;
  launch_args.swap(blender_args);
  launch_args.push_back("--");
  launch_args.insert(launch_args.end(), script_args.begin(), script_args.end());
  const int launch_argc = int(launch_args.size());
  launch_args.push_back(nullptr);
  return launch(launch_argc, launch_args.data());
}

/* Called by the embedded Python module on Blender's main thread. */
extern "C" void GHOST_iosFarmSetActive(bool active)
{
  UIApplication *app = UIApplication.sharedApplication;
  static BOOL previous = NO;
  if (active) {
    previous = app.idleTimerDisabled;
    app.idleTimerDisabled = YES;
  }
  else {
    app.idleTimerDisabled = previous;
  }
}
